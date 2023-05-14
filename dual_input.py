import logging
from flask import Flask, render_template_string, request, jsonify
import flask.cli
import threading

from typing import Callable
# from easyrepl import readl

# Disable Flask's default logging
log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

# really disable extra logging that they don't want you to disable lol: 
# https://github.com/cs01/gdbgui/issues/425#issuecomment-1086871191
# https://github.com/cs01/gdbgui/issues/425#issuecomment-1119836533
flask.cli.show_server_banner = lambda *args: None


app = Flask(__name__)
# HTML template
index_html = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Coding Assistant</title>
    <style>
        * {
            box-sizing: border-box;
        }

        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 0;
        }

        .container {
            max-width: 600px;
            margin: 0 auto;
        }

        .chat-header {
            text-align: center;
            padding: 1rem;
            border-bottom: 1px solid #ccc;
        }

        .chat-history {
            height: 300px;
            overflow-y: scroll;
            border: 1px solid #ccc;
            padding: 1rem;
        }

        .chat-controls {
            display: flex;
            margin-top: 1rem;
        }

        .chat-controls input {
            flex-grow: 1;
            padding: 0.5rem;
            border: 1px solid #ccc;
        }

        .chat-controls button {
            padding: 0.5rem;
            background-color: #007BFF;
            color: white;
            border: 1px solid #007BFF;
            cursor: pointer;
            width: 80px; /* Add a fixed width for the button */
            position: relative; // for centering the spinner
        }

        .chat-controls button:hover {
            background-color: #0056B3;
        }

        .chat-controls button:disabled {
            background-color: #ccc;
            border-color: #ccc;
            cursor: not-allowed;
        }

        .chat-controls button:disabled:hover {
            background-color: #ccc;
        }

        .button-loading::after {
            content: "";
            position: absolute;
            width: 16px;
            height: 16px;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            margin: auto;
            border: 4px solid transparent;
            border-top-color: #ffffff;
            border-radius: 50%;
            animation: button-loading-spinner 0.35s ease infinite;
        }

        @keyframes button-loading-spinner {
            from {
                transform: rotate(0turn);
            }
            to {
                transform: rotate(1turn);
            }
        }
    </style>
    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
</head>
<body>
    <div class="container">
        <div class="chat-header">
            <h2>Coding Assistant</h2>
        </div>
        <div id="chat_history" class="chat-history"></div>
        <div class="chat-controls">
            <input id="chat_input" type="text" placeholder="Type your message...">
            <button id="send_button">
                <span class="button_text">Send</span>
            </button>
        </div>
    </div>

    <script>
        function appendMessage(message) {
            $("#chat_history").append("<p>" + message + "</p>");
            $("#chat_history").scrollTop($("#chat_history")[0].scrollHeight);
        }

        function toggleSendButton(state) {
            $("#send_button").prop("disabled", !state);
            if (!state) {
                $(".button_text").addClass("button-loading");
                $(".button_text").text("");
            } else {
                $(".button_text").removeClass("button-loading");
                $(".button_text").text("Send");
            }
        }

        $("#send_button").click(function() {
            var message = $("#chat_input").val();
            if (!message) return;

            $("#chat_input").val("");
            appendMessage("You: " + message);

            toggleSendButton(false);

            $.post("/send_message", {message: message}, function(data) {
                appendMessage("AI: " + data.response);
                toggleSendButton(true);
            });
        });

        $("#chat_input").keypress(function(e) {
            if (e.which === 13) {  // Enter key
                $("#send_button").click();
            }
        });

        // Enable the send button when the page is ready
        $(document).ready(function() {
            toggleSendButton(true);
        });
    </script>
</body>
</html>
'''


chat_callback = None
"""
def chat_callback(message:str) -> str:
    # Process a user's message and return the AI's response
"""

terminal_callback = None
"""
def terminal_callback(command:str) -> None:
    # Execute command using os.system or subprocess
    # any output should be printed to the terminal
    # no value should be returned
"""

def register_chat_callback(callback:Callable[[str], str]):
    global chat_callback
    chat_callback = callback

def register_terminal_callback(callback:Callable[[str], None]):
    global terminal_callback
    terminal_callback = callback


@app.route("/")
def index():
    return render_template_string(index_html)

@app.route("/send_message", methods=["POST"])
def send_message():
    message = request.form["message"]

    assert chat_callback is not None, "chat_callback must be registered before running the Flask app"

    response = chat_callback(message)

    # # Process the message and respond with the AI's response
    # response = "AI response goes here"  # Replace with actual AI response

    return jsonify({"response": response})

# def command_input_loop():
#     assert terminal_callback is not None, "terminal_callback must be registered before running the Flask app"
#     while True:
#         # command_input = input(">>> ")
#         command_input = readl(prompt=">>> ")
#         terminal_callback(command_input)
#         # print(f"Executed: {command_input}")
#         # # Execute command_input using os.system or subprocess
#         # # ...


def run_dual_input():
    app_url = "http://127.0.0.1:5000"
    print(f"Chat Assistant at {app_url}")
    
    # start the thread with the terminal input
    # command_input_thread = threading.Thread(target=command_input_loop, daemon=True)
    # command_input_thread.start()

    # Set up the Flask app to run with minimal output
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)
