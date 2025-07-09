import os
import chainlit as cl
import logging
import time
from dotenv import load_dotenv
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.agents.models import CodeInterpreterTool
from azure.ai.agents import AgentsClient

# Load environment variables
print("Loading environment variables...")
load_dotenv("sample.env")

logger = logging.getLogger("azure.core.pipeline.policies.http_logging_policy")
logger.setLevel(logging.WARNING)

AIPROJECT_CONNECTION_STRING = os.getenv("AIPROJECT_CONNECTION_STRING")
AGENT_ID = os.getenv("AGENT_ID")

print("Loaded AGENT_ID:", AGENT_ID)
print("Loaded AIPROJECT_CONNECTION_STRING:", AIPROJECT_CONNECTION_STRING)
print("AIPROJECT_CONNECTION_STRING repr:", repr(AIPROJECT_CONNECTION_STRING))

if not AIPROJECT_CONNECTION_STRING or not AGENT_ID:
    raise ValueError("Missing AIPROJECT_CONNECTION_STRING or AGENT_ID in environment variables.")

print("Initializing AgentsClient...")
agents_client = AgentsClient(
    endpoint=AIPROJECT_CONNECTION_STRING,
    credential=DefaultAzureCredential()
)

code_interpreter = CodeInterpreterTool()

# Chainlit setup
@cl.on_chat_start
async def on_chat_start():
    print("on_chat_start triggered")
    if not cl.user_session.get("thread_id"):
        print("Creating new thread...")
        thread = agents_client.threads.create()
        cl.user_session.set("thread_id", thread.id)
        print(f"New Thread ID: {thread.id}")
    else:
        print("Thread already exists in session.")

@cl.on_message
async def on_message(message: cl.Message):
    print("on_message triggered")
    thread_id = cl.user_session.get("thread_id")
    print(f"On message Thread ID: {thread_id}")
    try:
        thinking_msg = await cl.Message("thinking...", author="agent").send()
        print("Thinking message sent.")

        # Add user message to the thread
        print("Creating user message...")
        msg_response = agents_client.messages.create(
            thread_id=thread_id,
            role="user",
            content=message.content,
        )
        print(f"Created message, ID: {msg_response.id}")

        # Create and run the agent
        print("Creating agent run...")
        run = agents_client.runs.create(
            thread_id=thread_id,
            assistant_id=AGENT_ID,
            #tools=[code_interpreter]
        )
        print(f"Run created: {run.id}, status: {run.status}")

        # Poll for completion
        print("Polling for run completion...")
        while run.status in ["queued", "in_progress", "requires_action"]:
            print(f"Current run status: {run.status}")
            time.sleep(1)
            run = agents_client.runs.get(thread_id=thread_id, run_id=run.id)

        print(f"Final run status: {run.status}")

        if run.status == "failed":
            print(f"Run failed: {run.last_error}")
            raise Exception(run.last_error)

        # Get all messages from the thread
        print("Listing all messages from the thread...")
        messages = agents_client.messages.list(thread_id=thread_id)
        last_msg = None
        message_list = messages.data if hasattr(messages, 'data') else messages

        if not message_list:
            print("No messages returned from the thread.")
            raise Exception("No messages returned from the thread.")

        print("Searching for last assistant message...")
        for msg_item in reversed(list(message_list)):
            print(f"Message role: {msg_item.role}")
            if msg_item.role == "assistant":
                last_msg = msg_item
                break

        if not last_msg:
            print("No response from the model.")
            raise Exception("No response from the model.")

        # Extract content
        print("Extracting content from last assistant message...")
        content = ""
        if hasattr(last_msg, 'content') and last_msg.content:
            for content_item in last_msg.content:
                print(f"Content item: {content_item}")
                if hasattr(content_item, 'text') and hasattr(content_item.text, 'value'):
                    content = content_item.text.value
                    break
                elif hasattr(content_item, 'text'):
                    content = str(content_item.text)
                    break

        print(f"Final assistant content: {content if content else 'No response received'}")
        thinking_msg.content = content if content else "No response received"
        await thinking_msg.update()

    except Exception as e:
        print(f"Exception occurred: {e}")
        await cl.Message(content=f"Error: {str(e)}").send()

if __name__ == "__main__":
    print("Script started.")
    pass