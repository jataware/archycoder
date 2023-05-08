# Archy Coder
Interactive coding session with GPT-4

## Getting Started
1. download/install archytas repo (https://github.com/jataware/archytas):
    ```
    # make sure poetry is installed
    pip install poetry

    # clone and install
    git clone git@github.com:jataware/archytas.git
    cd archytas
    poetry install

    # make sure OPENAI_API_KEY var is set
    # or pass it in as an argument to the agent
    export OPENAI_API_KEY="sk-..."
    ```

2. install other dependencies
    ```
    pip install flask
    pip install easyrepl
    ```

3. run the demo
    ```
    python copilot.py
    ```
    - input the name of a file that you want the AI edit. if it doesn't exist, it will be created
    - this is a terminal session, so you can run commands here (e.g. run the program you are working on). 
        - (WIP) eventually the AI will be able to see output/errors from running your program in here
        - but at the moment, there's no reason to use this terminal session over any other.

4. open http://127.0.0.1:5000 in your browser
    - you can ask the assistant to write programs, which will then show up in your file
    - the AI can see edits you make to the file, and will adjust its outputs accordingly
    - currently the AI can't see any results from running the file.
     
