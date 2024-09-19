import io
import os
import streamlit as st
import pandas as pd
import openai
from openai import AssistantEventHandler
from openai.types.beta.threads import Text, TextDelta

def ai_assistant_tab(df_filtered):
    # Custom CSS to make the input bar sticky
    st.markdown("""
        <style>
        /* Make the input bar sticky at the bottom */
        div[data-testid="stChatInput"] {
            position: fixed;
            bottom: 0;
            width: 100%;
            background-color: #262730;  /* Input bar colour */
            padding: 10px;
            z-index: 100;
            box-shadow: 0 -1px 3px rgba(0, 0, 0, 0.1);
        }
        /* Adjust the main content to prevent it from being hidden behind the input bar */
        .main .block-container {
            padding-bottom: 150px;  /* Adjust this value if needed */
        }
        /* Set the background colour of the entire app */
        .main {
            background-color: #0E1117;  /* Background colour */
            color: #FAFAFA;  /* Text colour */
        }
        /* Set the text colour in the input bar */
        div[data-testid="stChatInput"] textarea {
            color: #FAFAFA;  /* Text in input bar */
        }
        /* Set the placeholder text colour in the input bar */
        div[data-testid="stChatInput"] textarea::placeholder {
            color: #FAFAFA;
        }
        /* Style the chat messages */
        .stChatMessage {
            background-color: transparent;
        }
        .stChatMessage div {
            color: #FAFAFA;
        }
        /* Scrollbar styling */
        ::-webkit-scrollbar {
            width: 8px;
        }
        ::-webkit-scrollbar-track {
            background: #262730;
        }
        ::-webkit-scrollbar-thumb {
            background-color: #FAFAFA;
            border-radius: 10px;
        }
        </style>
        """, unsafe_allow_html=True)

    
    st.header("AI Assistant")
    st.write("Ask questions about your data, and the assistant will analyze it using Python code.")

    # Initialize OpenAI client using API keys from Streamlit secrets
    client = openai.Client(api_key=st.secrets["OPENAI_API_KEY"])

    # Use existing assistant ID from Streamlit secrets
    assistant_id = st.secrets["OPENAI_ASSISTANT_ID"]  
    assistant = client.beta.assistants.retrieve(assistant_id)

    # Convert dataframe to a CSV file using io.BytesIO
    csv_buffer = io.BytesIO()
    df_filtered.to_csv(csv_buffer, index=False)
    csv_buffer.seek(0)  # Reset buffer position to the start

    # Upload the CSV file as binary data
    file = client.files.create(
        file=csv_buffer,
        purpose='assistants'
    )

    # Update the assistant to include the file
    client.beta.assistants.update(
        assistant_id,
        tool_resources={
            "code_interpreter": {
                "file_ids": [file.id]
            }
        }
    )


    # Initialize session state variables
    if 'chat_history' not in st.session_state:
        st.session_state.chat_history = []
    if 'thread_id' not in st.session_state:
        thread = client.beta.threads.create()
        st.session_state.thread_id = thread.id

    # Create a container for the chat messages
    chat_container = st.container()

    # Display chat history in the container
    with chat_container:
        for message in st.session_state.chat_history:
            if message['role'] == 'user':
                st.chat_message("User").write(message['content'])
            else:
                st.chat_message("Assistant").write(message['content'])

    # User input
    if prompt := st.chat_input("Enter your question about the data"):
        # Add user message to chat history
        st.session_state.chat_history.append({'role': 'user', 'content': prompt})

        # Display the user's message immediately
        with chat_container:
            st.chat_message("User").write(prompt)

        # Create a new message in the thread
        client.beta.threads.messages.create(
            thread_id=st.session_state.thread_id,
            role="user",
            content=prompt
        )

        # Define event handler to capture assistant's response
        class MyEventHandler(AssistantEventHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.assistant_message = ""
                # Create a placeholder within the chat container
                with chat_container:
                    self.assistant_message_placeholder = st.chat_message("Assistant")

            def on_text_delta(self, delta: TextDelta, snapshot: Text, **kwargs):
                if delta and delta.value:
                    self.assistant_message += delta.value
                    # Update the assistant's message in the placeholder
                    self.assistant_message_placeholder.markdown(self.assistant_message)

        # Instantiate the event handler
        event_handler = MyEventHandler()

        # Run the assistant
        with client.beta.threads.runs.stream(
            thread_id=st.session_state.thread_id,
            assistant_id=assistant_id,
            event_handler=event_handler,
            temperature=0
        ) as stream:
            stream.until_done()

        # Add assistant's message to chat history
        st.session_state.chat_history.append({'role': 'assistant', 'content': event_handler.assistant_message})

        # Handle any files generated by the assistant
        messages = client.beta.threads.messages.list(thread_id=st.session_state.thread_id)
        for message in messages.data:
            if message.role == 'assistant' and hasattr(message, 'attachments') and message.attachments:
                for attachment in message.attachments:
                    if attachment.object == 'file':
                        file_id = attachment.file_id
                        # Download the file
                        file_content = client.files.content(file_id).read()
                        # Display the file content if appropriate
                        if attachment.filename.endswith('.png') or attachment.filename.endswith('.jpg'):
                            st.image(file_content)
                        elif attachment.filename.endswith('.csv'):
                            # Read CSV into a dataframe
                            df = pd.read_csv(io.BytesIO(file_content))
                            st.write(df)
                        else:
                            st.download_button(
                                label=f"Download {attachment.filename}",
                                data=file_content,
                                file_name=attachment.filename
                            )
