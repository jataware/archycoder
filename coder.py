from archytas.agent import Agent, no_spinner
from dual_input import run_dual_input, register_chat_callback, register_terminal_callback
import subprocess
import sys
from easyrepl import readl

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



def parse_program(message:str) -> str|None:
    """Parse a message to determine if it is a program. A program will start with ```python and end with"""
    chunks = message.split('```')

    code_blocks = [chunk for i, chunk in enumerate(chunks) if i % 2 == 1]

    if len(code_blocks) == 0:
        return None
    
    python_blocks = [block[6:].strip() for block in code_blocks if block.startswith('python')]
    if len(python_blocks) == 0:
        return None 

    assert len(python_blocks) == 1, f"Found multiple python blocks: {python_blocks}"
    return python_blocks


class ProgramManager:
    def __init__(self, filename:str):
        self.filename = filename

        # if file doesn't exist, create it
        with open(self.filename, 'a') as f:
            pass

        # TODO: some sort of chat history

        # save the current state of the program 
        # (start with blank program, so we know to tell LLM if file wasn't blank)
        self.current_program = ''

    def get_program(self) -> str:
        """Return the current program"""
        with open(self.filename, 'r') as f:
            return f.read()
    
    def update_program(self, new_program:str) -> None:
        """Update the program"""
        with open(self.filename, 'w') as f:
            f.write(new_program)
        self.current_program = new_program

    def is_program_changed(self) -> bool:
        """Return True if the program has changed since the last time it was checked"""
        return self.current_program != self.get_program()



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


    agent = Agent(prompt='''
You are a coding assistant. Your job is to help the user write a python program. 
Whenever you are asked to write code, you may describe your thought process, however any code must be contained within a pair of triple back-ticks ```.
Currently you are in DEBUG mode, so there are some extra things you should do:
- make sure there is only one program in your response
- don't tell the user about libraries they need to install
- don't worry about a full explanation of the code. You can skip straight to the code
''', spinner=no_spinner)


    def on_chat_message(message:str) -> str:
        """Process a user's message and return the AI's response"""
        nonlocal clear_context

        # if the program changed since the AI edited it, tell the AI
        if manager.is_program_changed():
            clear_context() # clear any previous code context
            clear_context = agent.add_managed_context(f'Context: The user modified the program. The current program is:\n```python\n{manager.get_program()}\n```')
        
        # send the user message to the agent, and get the response
        response = agent.query(message)

        # handle program
        prog = parse_program(response)
        if prog:
            assert len(prog) == 1, f"Found multiple programs: {prog}"
            manager.update_program(prog[0])
        
        # return the AI response for the UI to render
        return response

    def on_terminal_command(command:str) -> None:
        """Execute command using subprocess"""
        cmd = command.split(' ')
        subprocess.run(cmd)
        

    register_chat_callback(on_chat_message)
    register_terminal_callback(on_terminal_command)

    run_dual_input()
    


if __name__ == '__main__':
    main()