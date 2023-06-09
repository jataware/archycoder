from archytas.agent import Agent, no_spinner, Role, Message
from chat_window import run_chat_window, register_chat_callback, register_history_callback, ChatMessage
import argparse
from easyrepl import readl
import json
import os
import dirtyjson
from typing import Generator, TypedDict

import pdb



CONTEXT_PREFIX = 'Context: The current program is:\n'

role_map = {
    Role.user: 'You',
    Role.assistant: 'AI',
    Role.system: 'System'
}

class Edit(TypedDict):
    code: str
    start: int
    end: int


def json_block_iter(message:str) -> Generator[str|Edit, None, None]:
    """
    Iterator to extract text and json objects from the LLM message.
    """
    original_message = message #for debugging
    message = message.lstrip()
    while len(message) > 0:
        try:
            i = message.index('```json')
        except ValueError:
            message = message.lstrip()
            if message:
                yield message
            return
        
        if i != 0:
            yield message[:i]
            message = message[i:]
        
        message = message[7:].lstrip()
        if not message.startswith('{') and not message.startswith('['):
            pdb.set_trace()
            raise ValueError(f"Expected json block to start with {{ or [ but found {message}")
        
        #find candidate end indices
        delimiter = '}' if message.startswith('{') else ']'
        end_indices = [i for i, c in enumerate(message) if c == delimiter]

        #find the first end index that is valid json
        for end_index in end_indices:
            try:
                parsed_block = dirtyjson.loads(message[:end_index+1])
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"Failed to parse json block: {message}")
        
        # yield the block if single block, or sequentially yield each item in the list of blocks
        if isinstance(parsed_block, list):
            for item in parsed_block:
                assert 'code' in item and 'start' in item and 'end' in item, f"INTERNAL ERROR: Expected json block to have keys 'code', 'start', and 'end', but found {parsed_block}"
                yield dict(item)
        elif isinstance(parsed_block, dict):
            assert 'code' in parsed_block and 'start' in parsed_block and 'end' in parsed_block, f"INTERNAL ERROR: Expected json block to have keys 'code', 'start', and 'end', but found {parsed_block}"
            yield dict(parsed_block)
        else:
            raise ValueError(f"INTERNAL ERROR: Expected json block to be a dict or list, but found {parsed_block}")
        
        #update message to be the remaining text
        message = message[end_index+1:].lstrip()
        assert message.startswith('```'), f"INTERNAL ERROR: Expected json block to end with ``` but found {message}"
        message = message[3:].lstrip()
    return



def parse_program(message:str) -> tuple[list[Edit], str]:
    """
    Extract all code edits from a message.

    Edits are represented in the message with json blocks starting with ```json and ending with ```.
    Edits contain the following keys:
    - code: the code to be inserted
    - start: the start index of the code to be replaced
    - end: the end index of the code to be replaced

    Args:
        message: the message to parse from the LLM. Should contain json blocks wrapped in ```json and ending with ```.

    Returns:
        edits: a list of edits extracted from the message
        chat: the message with the edits removed
    """

    chunks = list(json_block_iter(message))
    edits = [b for b in chunks if isinstance(b, dict)]

    # convert the chunks into a chat message format: [start, end)\n{code}
    chat_chunks = [f'[{c["start"]}, {c["end"]})\n<code>{c["code"]}</code>' if isinstance(c, dict) else c.strip() for c in chunks]
    chat = '\n\n'.join(chat_chunks)

    return edits, chat


def add_line_numbers(program:str) -> str:
    """Add line numbers to a program. Line numbers start at 1"""
    lines = program.splitlines(keepends=True)
    width = len(str(len(lines)))
    return ''.join([f"{i+1:>{width}}| {line}" for i, line in enumerate(lines)])


def insert_line(text: str, line: str, i: int, newline:str='\n') -> str:
    """
    Insert a line into a text string at the specified line number.

    Maintains the original line endings of the text, and assume that the input line has a line ending.

    Args:
        text (str): the text to insert the line into
        line (str): the line to insert
        i (int): the line number to insert the line at. line 1 is the first line of the text
        newline (str, optional): the line ending to use for the inserted line. Defaults to '\n'.

    Raises:
        ValueError: if i is not a valid line number

    Returns:
        str: the text with the line inserted
    """
    # Split the text into lines
    lines = text.splitlines(keepends=True)


    # check if i is within the range of the text lines, and convert to 0-indexed
    if i < 1 or i > len(lines)+1:
        raise ValueError(f"Invalid line number: {i}. Must be between 1 and {len(lines)+1}")
    i -= 1

    #if inserting at the end, and the last line didn't have a line ending, add one
    if i == len(lines) and not lines[-1].endswith(newline):
        lines[-1] += newline

    # Insert the new line at the specified position i
    lines.insert(i, line)

    # Join the lines back together using the original line ending and return the result
    return ''.join(lines)


def get_clean_chat_history(messages:list[Message]) -> list[Message]:
    """
    Filter out any context messages the system inserted into the chat containing the current state of the program.
    """
    return [message for message in messages if not (message['role'] == Role.system and message['content'].startswith(CONTEXT_PREFIX))]



def sorted_edits(edits:list[Edit]) -> list[Edit]:
    """
    sort edits by start/end indices
    raise error if edits overlap
    """
    sorted_edits = sorted(edits, key=lambda e: (e['start'], e['end']))
    for i in range(len(sorted_edits)-1):
        if sorted_edits[i]['end'] > sorted_edits[i+1]['start']:
            raise ValueError(f"Edits overlap: {sorted_edits[i]} and {sorted_edits[i+1]}")
    return sorted_edits


class ProgramManager:
    def __init__(self, filename:str):
        self.filename = filename

        # if file doesn't exist, create it
        if not os.path.exists(self.filename):
            with open(self.filename, 'a') as f: pass 

        # save the current state of the program 
        # (start with blank program, so we know to tell LLM if file wasn't blank)
        self.current_program = ''
        self.chat_history_filename = f"{os.path.splitext(self.filename)[0]}.chat" 
    

    def get_program(self) -> str:
        """Return the current program"""
        with open(self.filename, 'r') as f:
            return f.read()
    
    def update_program(self, code:str, start:int, end:int) -> None:
        """Update the program"""
        with open(self.filename, 'r') as f:
            program = f.read()
        
        # insert edits into the program via git merge syntax
        # <<<<<<< Original Code
        # <original code>
        # =======
        # <suggested code>
        # >>>>>>> LLM Suggestion
        newline = '\r\n' if '\r\n' in program else '\n' #detect the line ending
        if len(code) > 0 and not code.endswith(newline): 
            code += newline # ensure the code ends with a newline
        new_program = insert_line(program, f"<<<<<<< Original Code{newline}", start, newline)
        new_program = insert_line(new_program, f"======={newline}", end+1, newline)
        new_program = insert_line(new_program, f"{code}>>>>>>> LLM Suggestion{newline}", end+2, newline)

        with open(self.filename, 'w') as f:
            f.write(new_program)
        
        self.current_program = new_program

    def is_program_changed(self) -> bool:
        """Return True if the program has changed since the last time it was checked"""
        return self.current_program != self.get_program()


    def load_chat_history(self) -> list:
        history = []
        if os.path.exists(self.chat_history_filename):
            with open(self.chat_history_filename, 'r') as f:
                history = json.load(f)
        
        #filter out context messages
        history = get_clean_chat_history(history)

        return history
    
    def save_chat_history(self, history: list) -> None:
        #filter out context messages
        history = get_clean_chat_history(history)
        with open(self.chat_history_filename, 'w') as f:
            json.dump(history, f)


coder_prompt = '''
You are a coding assistant. Your job is to help the user write a python program. 
Whenever you are asked to write code, you may describe your thought process, however ALL CODE MUST BE CONTAINED IN VALID JSON OBJECTS:
```json
{
    "code":  #your code here as a string with any necessary whitespace
    "start": #the line number where your code start being inserted (inclusive). Must be >= 1 and <= the number of lines in the program
    "end":   #the line number where your code stops being inserted (exclusive). Must be >= 1 and <= the number of lines in the program
             #i.e. code from lines start (inclusive) to end (exclusive) will be replaced by your code
             #if start == end, this means an insertion without any replacement
}
```
If you want to modify multiple parts of the program, you may include multiple code blocks in your response as separate json objects.

# Examples

lets say you want to make multiple modifications to the code, each modification must be a separate json object. 
For example, lets say the code looks like this:
```python
1| def add(a, b):
2|     return a + b
3|
4| def multiply(a, b):
5|     return a * b
```
and the user asks you to change the add function to take an arbitrary number of arguments, and also add a divide function. You could respond with:
    I made this replacement for the add function:
    ```json
    {
        "code": "def add(*args):\n    return sum(args)\n",
        "start": 1,
        "end": 3
    }
    ```
    And I made a new divide function:
    ```json
    {
        "code": "\ndef divide(a, b):\n    return a / b",
        "start": 6,
        "end": 6
    }
    ```
Alternatively you can bundle all the changes up into a single json list of objects:
    I made the changes you requested:
    ```json
    [
        {
            "code": "def add(*args):\n    return sum(args)\n",
            "start": 1,
            "end": 3
        },
        {
            "code": "\ndef divide(a, b):\n    return a / b",
            "start": 6,
            "end": 6
        }
    ]
    ```
The resulting code would look like this:
```python
1| def add(*args):
2|     return sum(args)
3|
4| def multiply(a, b):
5|     return a * b
6|
7| def divide(a, b):
8|     return a / b
```


Another example. Say the user's code looks like this:
```python
<earlier code omitted>
60|         .chat-controls input {
61|             flex-grow: 1;
62|             padding: 0.5rem;
63|             border: 1px solid #ccc;
64|         }
<later code omitted>
```

Here's an example of a correctly formatted code modification that overwrites the original:

```json
{
    "code": "        .chat-controls input {
            flex-grow: 1;
            padding: 0.5rem;
            border: 1px solid #ccc;
            resize: none;
            overflow: auto;
            min-height: 20px;
            max-height: 100px;
        }
",
    "start": 60,
    "end": 65
}
```

The resulting code will look like this:

```python
60|         .chat-controls input {
61|             flex-grow: 1;
62|             padding: 0.5rem;
63|             border: 1px solid #ccc;
64|             resize: none;
65|             overflow: auto;
66|             min-height: 20px;
67|             max-height: 100px;
68|         }
```

In this example, the entire code block is included, the indentation is correct, and the "start" and "end" values are accurate. The existing spacing is maintained, and only the necessary changes are made.


# Instructions
When providing code modifications, make sure to:
- Do not include line numbers in your code. The user's code will display line numbers so you know where to insert, but line numbers are not a part of the code itself
- Follow the existing style of the user's code. This includes things like variable names, whitespace, and indentation, and making your edits fit the surrounding code.
- Faithfully reproduce comments and docstrings, including the indentation, in your edits. If your edit makes the comment/docstring incorrect, you should edit it to say the correct thing.
- Specify the correct line numbers for the "start" and "end" values in the JSON object. All lines from the start line, up to but not including the end line will be included in the selection.
- Prefer multiple small edits over one large edit. Basically if an edit would contain lines copied verbatim, break it up into smaller more targeted edits.
- Do not show the resulting code in your chat output. The user can already see it in their code editor.
- Don't tell the user about libraries they need to install, unless it is a particularly uncommon library. Assume the user has most common libraries e.g. numpy, pandas, etc.
- Don't give full explanations of the code. You should be succinct and to the point. If the user wants more explanation, they can ask for it
- Use the past tense when talking about changes to code. e.g. "I added a function" instead of "I will add a function"
'''

def set_current_program_context(manager: ProgramManager, agent: Agent) -> None:
    """
    Adds the current program context to the chat history as a timed context

    This lets the LLM see the current state of the program so it can make its edits.
    This should be called every time before a user message is sent to the llm
    """
    lined_program = add_line_numbers(manager.get_program())
    agent.add_timed_context(f"{CONTEXT_PREFIX}```python\n{lined_program}```")


def parse_args():
    parser = argparse.ArgumentParser(description='Coding Assistant')
    parser.add_argument('file_path', help='(optional) name of the code file', nargs='?')
    parser.add_argument('--clear-history', action='store_true', help='clear chat history')
    args = parser.parse_args()

    # handle optional file path
    if args.file_path is None:
        args.file_path = readl(prompt="What would you like to name your code file? ")

    return args

def main():
    args = parse_args()
    file_path = args.file_path

    manager = ProgramManager(file_path)
    agent = Agent(prompt=coder_prompt, spinner=no_spinner)

    # Load chat history if it exists
    if not args.clear_history:
        agent.messages = manager.load_chat_history()

    # initialize the program context
    set_current_program_context(manager, agent)
        

    def on_get_chat_history() -> list[ChatMessage]:
        """Return the chat history (converting any LLM messages into properly formatted edit blocks)"""
        messages = []
        for message in get_clean_chat_history(agent.messages):
            if message['role'] == Role.assistant:
                # convert LLM messages into lists of edits
                _, chat = parse_program(message['content'])
                messages.append(ChatMessage(role='AI', content=chat))
            else:
                #copy all other messages verbatim
                messages.append(ChatMessage(role=role_map[message['role']], content=message['content']))

        return messages
    
    def on_chat_message(message:str) -> list[ChatMessage]:
        """Process a user's message and return the AI's response"""
        
        # if the program changed since the AI edited it, tell the AI
        if manager.is_program_changed():
            # slightly hacky way to clear all program context messages, but keep error context messages
            # TODO: look into archytas having a method for clearing specific types of context messages
            while len(agent._context_lifetimes) > 0:
                agent.update_timed_context()
            set_current_program_context(manager, agent)

        # send the user message to the agent, and get the response
        raw_response = agent.query(message)
        response = []

        # handle program
        try:
            edits, chat = parse_program(raw_response)
        except Exception as e:
            edits, chat = [], f"Error parsing response: {e}"
            response.append(ChatMessage(role='System', content=chat))
            agent.add_permanent_context(chat)

        response.append(ChatMessage(role='AI', content=chat))

        #sort the edits by start line number
        try:
            edits = reversed(sorted_edits(edits))
        except Exception as e:
            edits, msg = [], f"Error sorting edits: {e}"
            response.append(ChatMessage(role='System', content=msg))
            agent.add_permanent_context(msg)

        # insert edits into the program
        for edit in edits:
            try:
                manager.update_program(edit['code'], edit['start'], edit['end'])
            except Exception as e:
                msg = f"Error: {e} while handling edit {edit}"
                response.append(ChatMessage(role='System', content=msg))
                agent.add_permanent_context(msg)
        
        manager.save_chat_history(agent.messages)


        # return the AI response for the UI to render
        # TODO: AI response loses formatting. also doesn't have code highlighting...
        return response

    # regester callbacks for the UI
    register_chat_callback(on_chat_message)
    register_history_callback(on_get_chat_history)

    # run the UI
    run_chat_window()
    


if __name__ == '__main__':
    main()