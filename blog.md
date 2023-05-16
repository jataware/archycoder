# Coding with ChatGPT
ChatGPT (especially GPT-4) is an excellent tool for assisting with writing code. My one gripe is that if ChatGPT writes code for me, as soon as I copy it over to my editor and start using it and making changes, the code I have, and the code ChatGPT thinks I have, start getting out of sync. Copying the code back and forth to manually keep them in sync is quite tedious. So I made a quick and dirty tool to solve this problem.

# Introducing ArchyCoder
Interactively editing code with GPT-4
<div align="center">
  <a href="https://www.youtube.com/watch?v=-I0BAw2HOIA">
    <img src="assets/demo.gif" alt="Watch the video">
  </a>
  <br/>
  click to watch original video on youtube
</div>
<br/>

ArchyCoder is a minimal python program that runs a basic AI chat window in the browser where you can talk to GPT-4, and interactively edit a file. Any updates you make to the file are presented to GPT-4 as context, and GPT-4 can suggest code edits which will show up in your editor.

Process:
1. start ArchyCoder in the terminal
2. specify a file to watch
3. open the chat window
4. open your editor of choice
5. profit

# How it works
ArchyCoder leverages the [Archytas library](https://github.com/jataware/archytas) which provides a convenient code-based chat interface with GPT-4 through its `Agent` class. ArchyCoder runs a small flask UI, and a python script for managing the interaction with GPT-4. When you send a message in the UI, it gets forwarded to GPT-4 (via the OpenAI API) along with a copy of the current file contents. The response from GPT-4 is then parsed for code edits, which are then copied into the file using git-style conflict markers (i.e. `<<<<<<<`, `=======`, and `>>>>>>>`). Any code editor can be used, but I recommend one that supports handling conflict markers, e.g. VSCode. In your editor, you can accept or reject the suggested code changes, save, and then go back to the chat to ask the for more suggestions, all without having to copy changes back back and forth!

# Final Thoughts
It's still got some rough edges, but I find it useful enough to use over ChatGPT's online interface--at least until microsoft releases their mythical [Copilot X](https://www.youtube.com/watch?v=4RfD5JiXt3A) update. In the meantime though, ArchyCoder definitely has potential! I hope you'll give it a try!