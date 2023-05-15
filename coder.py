from archytas.agent import Agent, no_spinner, Role, Message
from chat_window import run_chat_window, register_chat_callback, register_history_callback, ChatMessage
import subprocess
import sys
from easyrepl import readl
import json
import os
import dirtyjson
from typing import Generator, TypedDict

import pdb



#TODO:
# [important]
# - capture the stdout from running the program, and save it for sending to the agent

# [nice to haves]
# - git merge/rebase interface for merging in AI's changes
# - take input arg for file to watch
# - save chat history. chat history should be loaded into the html page window on load
# - folder for chat histories
# - chat history is named <watch_file>.history
# - agent.py. should have a member variable for the loading context. The can pass in a no-op if don't want the spinner in the terminal
# - prettier rendering of the chat window + code highlighting
# - is there a way to stream the llm text the same way that chatgpt does?



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

    # convert the chunks into a chat message format: [start+1, end+1)\n{code}
    chat_chunks = [f'[{c["start"]}, {c["end"]})\n{c["code"]}' if isinstance(c, dict) else c.strip() for c in chunks]
    chat = '\n\n'.join(chat_chunks)

    return edits, chat


def add_line_numbers(program:str) -> str:
    """Add line numbers to a program. Line numbers start at 0"""
    lines = program.splitlines(keepends=True)
    width = len(str(len(lines)))
    return ''.join([f"{i+1:>{width}}| {line}" for i, line in enumerate(lines)])


def insert_line(text: str, line: str, i: int) -> str:
    """
    Insert a line into a text string at the specified line number.

    Maintains the original line endings of the text, and assume that the input line has a line ending.

    Args:
        text (str): the text to insert the line into
        line (str): the line to insert
        i (int): the line number to insert the line at. line 1 is the first line of the text

    Raises:
        ValueError: if i is not a valid line number

    Returns:
        str: the text with the line inserted
    """
    # Split the text into lines
    lines = text.splitlines(keepends=True)

    
    # Convert to 0-indexed, and check if i is within the range of the text lines
    i -= 1
    if i < 0 or i > len(lines):
        raise ValueError(f"Invalid line number: {i}. Must be between 0 and {len(lines)}")

    # Insert the new line at the specified position i
    lines.insert(i, line)

    # Join the lines back together using the original line ending and return the result
    return ''.join(lines)


def get_context_free_messages(messages:list[Message]) -> list[Message]:
    """
    Filter out any context messages the system inserted into the chat.
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
            os.makedirs("sessions", exist_ok=True) 
            self.filename = os.path.join("sessions", self.filename)
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
        new_program = insert_line(program, f"<<<<<<< Original Code{newline}", start)
        new_program = insert_line(new_program, f"======={newline}", end+1)
        new_program = insert_line(new_program, f"{code}>>>>>>> LLM Suggestion{newline}", end+2)

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
        history = get_context_free_messages(history)

        return history
    
    def save_chat_history(self, history: list) -> None:
        #filter out context messages
        history = get_context_free_messages(history)
        with open(self.chat_history_filename, 'w') as f:
            json.dump(history, f)


coder_prompt = '''
You are a coding assistant. Your job is to help the user write a python program. 
Whenever you are asked to write code, you may describe your thought process, however ALL CODE MUST BE CONTAINED IN VALID JSON OBJECTS:
```json
{
    "code":  #your code here as a string with any necessary whitespace
    "start": #the line number where your code start being inserted (inclusive)
    "end":   #the line number where your code stops being inserted (exclusive)
             #i.e. code from lines start (inclusive) to end (exclusive) will be replaced by your code
             #if start == end, this means an insertion without any replacement
}
```
If you want to modify multiple parts of the program, you may include multiple code blocks in your response as separate json objects.

# Examples
For example, if the current program is empty, and the user asks you to write a function that returns the sum of two numbers, you could respond with:
    Sure, I can help you with that. Here is the code:
    ```json
    {
        "code": "def add(a, b):\n    return a + b\n",
        "start": 1,
        "end": 1
    }
    ```

And the resulting code would look like this:
```python
1| def add(a, b):
2|     return a + b
```

Another example. Say the user's code looks like this:
```python
1| def add(a, b):
2|     return a + b
3|
4| def multiply(a, b):
5|     return a * b
```
And the user asks you to write a subtract function. You could respond with:
    I inserted a subtract function in your code:
    ```json
    {
        "code": "def subtract(a, b):\n    return a - b\n\n",
        "start": 4,
        "end": 4
    }
    ```
the resulting code would look like this:
```python
1| def add(a, b):
2|     return a + b
3|
4| def subtract(a, b):
5|     return a - b
6|
7| def multiply(a, b):
8|     return a * b
```
Notice how in this case, you specify that the code starts and ends on line 4 through 4, which means you are inserting code on line 4, without replacing anything.
Also notice how you added a newline to the end of your code, this is because the code on line 4 already ends with a newline, so you need to add another one to make sure the original spacing is preserved.

Lets say we have the same code example, and the user asks to make the add function take an arbitrary number of arguments. You can overwrite the function like so:
    I overwrote the add function with a new version that takes an arbitrary number of arguments:
    ```json
    {
        "code": "def add(*args):\n    return sum(args)\n",
        "start": 1,
        "end": 3
    }
    ```
The resulting code would look like this:
```python
1| def add(*args):
2|     return sum(args)
3|
4| def multiply(a, b):
5|     return a * b
```
Notice how this version will start at line 1 and overwrite 2 (end-start == 3-1 == 2) lines (thus overwriting the original function)

Let's say we have this code:
```python
1| import math
2| import numpy as np
3|
4| def add(a, b):
5|     return a + b
6|
7| def multiply(a, b):
8|     return a * b
```
And the user asks you to add a new function to the very start of the program, and delete the multiply function. You could respond with:
    I added a new function to the start of your program:
    ```json
    {
        "code": "def divide(a, b):\n    return a / b\n\n",
        "start": 1,
        "end": 1
    }
    ```
    I also deleted the multiply function:
    ```json
    {
        "code": "",
        "start": 7,
        "end": 9
    }
    ```
The resulting code would look like this:
```python
 1| def divide(a, b):
 2|     return a / b
 3|
 4| import math
 5| import numpy as np
 6|
 7| def add(a, b):
 8|     return a + b
 9|
```

Now let's say the user asks you to add a check if the user inputs a 0 to the divide function. You could respond with:
    I added a check to the divide function:
    ```json
    {
        "code": "    if b == 0:\n        return 0\n",
        "start": 2,
        "end": 2
    }
    ```
The resulting code would look like this:
```python
 1| def divide(a, b):
 2|     if b == 0:
 3|         return 0
 4|     return a / b
 5|
 6| import math
 7| import numpy as np
 8|
 9| def add(a, b):
10|     return a + b
11|
```
Notice how you had to include extra indentation to make sure the resulting code is indented correctly.


Lastly, lets say you want to make multiple modifications to the code, each modification must be a separate json object. 
For example, lets say its the same code example, and the user asks you to change the add function to take an arbitrary number of arguments, and also add a divide function. You could respond with:
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


# Instructions
When providing code modifications, make sure to:
- Do not include line numbers in your code. The user's code will display line numbers so you know where to insert, but line numbers are not a part of the code itself
- Follow the existing style of the user's code
- Include the entire code block that needs to be modified, including the opening and closing braces or parentheses.
- Ensure that the indentation of the new code matches the surrounding code.
- Specify the correct line numbers for the "start" and "end" values in the JSON object. All lines from the start line, up to but not including the end line will be included in the selection.
- Only write code/changes that are necessary. Do not overwrite existing code if it is not necessary, unless you are deleting it.
- Don't tell the user about libraries they need to install, unless it is a particularly uncommon library. Assume the user has most common libraries e.g. numpy, pandas, etc.
- Don't give full explanations of the code. You should be succinct and to the point. If the user wants more explanation, they can ask for it
- Use the past tense when talking about changes to code. e.g. "I added a function" instead of "I will add a function"


# More Examples

Say the user's code looks like this:
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

By following these revised instructions and examples, future interactions should be more efficient and accurate.
'''

def set_current_program_context(manager: ProgramManager, agent: Agent) -> None:
    """
    Adds the current program context to the chat history as a timed context

    This lets the LLM see the current state of the program so it can make its edits.
    This should be called every time before a user message is sent to the llm
    """
    lined_program = add_line_numbers(manager.get_program())
    agent.add_timed_context(f"{CONTEXT_PREFIX}```python\n{lined_program}```")


def main():
    if len(sys.argv) < 2:
        file_path = readl(prompt="What would you like to name your code file? ")
    else:
        file_path = sys.argv[1]


    manager = ProgramManager(file_path)
    agent = Agent(prompt=coder_prompt, spinner=no_spinner)

    # Load chat history if it exists
    if '--clear-history' not in sys.argv:
        agent.messages = manager.load_chat_history()

    # initialize the program context
    set_current_program_context(manager, agent)
        

    def on_get_chat_history() -> list[ChatMessage]:
        """Return the chat history"""
        messages = get_context_free_messages(agent.messages)
        messages = [ChatMessage(role=role_map[message['role']], content=message['content']) for message in messages]
        return messages
    
    def on_chat_message(message:str) -> str:
        """Process a user's message and return the AI's response"""
        
        # if the program changed since the AI edited it, tell the AI
        if manager.is_program_changed():
            agent.clear_all_context()
            set_current_program_context(manager, agent)

        # send the user message to the agent, and get the response
        response = agent.query(message)

        # handle program
        edits, chat = parse_program(response)

        # insert edits into the program
        for edit in reversed(sorted_edits(edits)):
            manager.update_program(edit['code'], edit['start'], edit['end'])
        
        manager.save_chat_history(agent.messages)

        #TODO: should this be displayed in the chat window?
        #      right now, if the user refreshes, it will show up in the window
        set_current_program_context(manager, agent)

        # return the AI response for the UI to render
        # TODO: AI response loses formatting. also doesn't have code highlighting...
        return chat

    # regester callbacks for the UI
    register_chat_callback(on_chat_message)
    register_history_callback(on_get_chat_history)

    # run the UI
    run_chat_window()
    


if __name__ == '__main__':
    main()