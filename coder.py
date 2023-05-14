from archytas.agent import Agent, no_spinner
from dual_input import run_dual_input, register_chat_callback, register_terminal_callback
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
    chat_chunks = [f'[{c["start"]+1}, {c["end"]+1})\n{c["code"]}' if isinstance(c, dict) else c.strip() for c in chunks]
    chat = '\n\n'.join(chat_chunks)

    return edits, chat


def add_line_numbers(program:str) -> str:
    """Add line numbers to a program. Line numbers start at 0"""
    lines = program.splitlines(keepends=True)
    width = len(str(len(lines)))
    return ''.join([f"{i:>{width}}| {line}" for i, line in enumerate(lines)])


def insert_line(text: str, line: str, i: int) -> str:
    """
    Insert a line into a text string at the specified line number.

    Maintains the original line endings of the text, and assume that the input line has a line ending.

    Args:
        text (str): the text to insert the line into
        line (str): the line to insert
        i (int): the line number to insert the line at. line 0 is the first line of the text

    Raises:
        ValueError: if i is not a valid line number

    Returns:
        str: the text with the line inserted
    """
    # Split the text into lines
    lines = text.splitlines(keepends=True)
    
    # Check if i is within the range of the text lines
    if i < 0 or i > len(lines):
        raise ValueError(f"Invalid line number: {i}. Must be between 0 and {len(lines)}")

    # Insert the new line at the specified position i
    lines.insert(i, line)

    # Join the lines back together using the original line ending and return the result
    return ''.join(lines)


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
        new_program = insert_line(program, f"<<<<<<< Original Code{newline}", start)
        new_program = insert_line(new_program, f"======={newline}", end+1)
        new_program = insert_line(new_program, f"{code}{newline}>>>>>>> LLM Suggestion{newline}", end+2)
        
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
        prefix = 'Context: The user modified the program. The current program is:\n```python\n'
        history = [message for message in history if not (message['role'] == 'system' and message['content'].startswith(prefix))]

        print(f"Loaded {len(history)} messages from {self.chat_history_filename}")
        for message in history:
            print(f"{message['role']}: {message['content']}")

        return history
    
    def save_chat_history(self, chat_history: list) -> None:
        with open(self.chat_history_filename, 'w') as f:
            json.dump(chat_history, f)


coder_prompt = '''
You are a coding assistant. Your job is to help the user write a python program. 
Whenever you are asked to write code, you may describe your thought process, however ALL CODE MUST BE CONTAINED IN VALID JSON OBJECTS:
```json
{
    "code":  #your code here as a string
    "start": #the line number where your code should be inserted
    "end":   #the line number where your code should end
}
```
If you want to modify multiple parts of the program, you may include multiple code blocks in your response as separate json objects.

For example, if the user asks you to write a function that returns the sum of two numbers, you could respond with:
    Sure, I can help you with that. Here is the code:
    ```json
    {
        "code": "def add(a, b):\n    return a + b",
        "start": 0,
        "end": 0
    }
    ```

Another example. Say the user's code looks like this:
```python
0| def add(a, b):
1|     return a + b
2| 
3| def multiply(a, b):
4|     return a * b
```
And the user asks you to write a subtract function. You could respond with:
    I inserted a subtract function in your code:
    ```json
    {
        "code": "def subtract(a, b):\n    return a - b\n\n",
        "start": 3,
        "end": 3
    }
    ```

Notice how in this case, you specify that the code is inserted on line 3

Lets say we have the same code example, and the user asks to make the add function take an arbitrary number of arguments. You can overwrite the function like so:
    I overwrote the add function with a new version that takes an arbitrary number of arguments:
    ```json
    {
        "code": "def add(*args):\n    return sum(args)",
        "start": 0,
        "end": 2
    }
    ```

Notice how this version will start at line 0 and overwrite 2 lines (thus overwriting the original function)

Lastly, lets say you want to make multiple modifications to the code, each modification must be a separate json object. 
For example, lets say its the same code example, and the user asks you to change the add function to take an arbitrary number of arguments, and also add a divide function. You could respond with:
    I made this replacement for the add function:
    ```json
    {
        "code": "def add(*args):\n    return sum(args)",
        "start": 0,
        "end": 2
    }
    ```
    And I made a new divide function:
    ```json
    {
        "code": "    return a * b\n\ndef divide(a, b):\n    return a / b\n\n",
        "start": 4,
        "end": 4
    }
    ```
Alternatively you can bundle all the changes up into a single json list
    I made the changes you requested:
    ```json
    [
        {
            "code": "def add(*args):\n    return sum(args)",
            "start": 0,
            "end": 2
        },
        {
            "code": "    return a * b\n\ndef divide(a, b):\n    return a / b\n\n",
            "start": 4,
            "end": 4
        }
    ]
    ```

Notice how for appending to the end of the code, since there's no newline, you have to start with the last line number

# Tips/Notes
- DO NOT INCLUDE LINE NUMBERS IN YOUR CODE. The user's code will display line numbers so you know where to insert, but line numbers are not a part of the code itself.
- follow the style of the user's code
- code edits start before the start line, and go up to, but not including the end line
- only write code/changes that are necessary. Do not overwrite existing code if it is not necessary.
- don't tell the user about libraries they need to install, unless it is a particularly uncommon library. Assume the user has most common libraries e.g. numpy, pandas, etc.
- don't give full explanations of the code. You should be succinct and to the point. If the user wants more explanation, they can ask for it.
- use the past tense when talking about changes to code. e.g. "I added a function" instead of "I will add a function"
'''




def main():
    if len(sys.argv) > 2:
        print("ERROR: too many command-line arguments.\nUsage: python copilot.py [optional_file_to_watch.py]")
        exit(1)
    elif len(sys.argv) < 2:
        file_path = readl(prompt="What would you like to name your code file? ")
    else:
        file_path = sys.argv[1]

    manager = ProgramManager(file_path)
    clear_context = lambda: ...

    agent = Agent(prompt=coder_prompt, spinner=no_spinner)

    #TODO: loaded history should be displayed in the chat window
    # agent.messages = manager.load_chat_history()

    def on_chat_message(message:str) -> str:
        """Process a user's message and return the AI's response"""
        nonlocal clear_context
        print(f'User: {message}')

        # if the program changed since the AI edited it, tell the AI
        if manager.is_program_changed():
            clear_context() # clear any previous code context
            lined_prog = add_line_numbers(manager.get_program())
            clear_context = agent.add_managed_context(f'Context: The user modified the program. The current program is:\n```python\n{lined_prog}\n```')
            #this should display the current code in the chat window
        
        # send the user message to the agent, and get the response
        response = agent.query(message)

        # handle program
        edits,chat = parse_program(response)
        
        # ########DEBUG#########
        # if edits:
        #     print(edits)
        #     print(add_line_numbers(manager.get_program()))
        # ######################

        # update the start/end line numbers of the edits to account for space added by previous edits
        offset = 0
        for edit in edits:
            edit['start'] += offset
            edit['end'] += offset
            offset += len(edit['code'].splitlines()) - (edit['end'] - edit['start']) + 3 # +3 for the # <<<<<<< ======= and >>>>>>> lines

        # insert edits into the program
        for edit in edits:
            manager.update_program(edit['code'], edit['start'], edit['end'])
        
        manager.save_chat_history(agent.messages)

        # return the AI response for the UI to render
        # TODO: AI response loses formatting. also doesn't have code highlighting...
        return chat

    # def on_terminal_command(command:str) -> None:
    #     """Execute command using subprocess"""
    #     cmd = command.split(' ')
    #     subprocess.run(cmd)
        

    register_chat_callback(on_chat_message)
    # register_terminal_callback(on_terminal_command)

    run_dual_input()
    


if __name__ == '__main__':
    main()