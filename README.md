# ArchyCoder
Interactive coding session with GPT-4

# Demo
Short demo of using ArchyCoder interactively to help edit an existing python file.
<div align="center">
  <a href="https://www.youtube.com/watch?v=-I0BAw2HOIA">
    <img src="assets/demo.gif" alt="Watch the video">
  </a>
  <br/>
  click to watch original video on youtube
</div>

## Getting Started
1. Install dependencies
    ```
    pip install -r requirements.txt
    ```

2. Set openai api key:
    ```
    export OPENAI_API_KEY="sk-..."
    ```

3. Run the demo
    ```
    python coder.py [file_to_edit.py]
    ```
    - Input the name of a file that you want the AI edit. if it doesn't exist, it will be created at the specified path.

4. Run the chat window: http://127.0.0.1:5000
    - You can ask the assistant to write programs, which will then show up in your file via git-style conflict markers (e.g. `<<<<<<<`, `=======`, `>>>>>>>`)
    - The AI can see edits you make to the file, and will adjust its outputs accordingly
    - If you want the AI to see any errors, or results from running the code, you have to copy it into the chat window

## Tips
- If the AI seems to be stuck, check the terminal for any errors. But sometimes it just takes a while to respond.
- Pass the `--clear-history` flag to start a chat without loading any previous history
- If you want to restart, you should both restart the terminal and refresh the browser
- Occasionally the AI will miss including some lines of code in the lines it selects for edits. So pay attention to the diff markers, and make sure to move over any lines that the AI missed
