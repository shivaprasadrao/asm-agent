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
load_dotenv("sample.env")

logger = logging.getLogger("azure.core.pipeline.policies.http_logging_policy")
logger.setLevel(logging.WARNING)

AIPROJECT_CONNECTION_STRING = os.getenv("AIPROJECT_CONNECTION_STRING")
AGENT_ID = os.getenv("AGENT_ID")

print("Loaded AGENT_ID:", AGENT_ID)
print("Loaded AIPROJECT_CONNECTION_STRING:", AIPROJECT_CONNECTION_STRING)
print("AIPROJECT_CONNECTION_STRING repr:", repr(AIPROJECT_CONNECTION_STRING))

# Use from_connection_string for azure-ai-projects 1.0.0b12
agents_client = AgentsClient(
    endpoint=AIPROJECT_CONNECTION_STRING,
    credential=DefaultAzureCredential()
)

code_interpreter = CodeInterpreterTool()

# Chainlit setup
@cl.on_chat_start
async def on_chat_start():
    if not cl.user_session.get("thread_id"):
        thread = agents_client.threads.create()
        cl.user_session.set("thread_id", thread.id)
        print(f"New Thread ID: {thread.id}")

@cl.on_message
async def on_message(message: cl.Message):
    thread_id = cl.user_session.get("thread_id")
    try:
        thinking_msg = await cl.Message("thinking...", author="agent").send()

        # Add user message to the thread
        msg_response = agents_client.messages.create(
            thread_id=thread_id,
            role="user",
            content=message.content,
        )
        print(f"Created message, ID: {msg_response.id}")

        # Create and run the agent
        run = agents_client.runs.create(
            thread_id=thread_id,
            assistant_id=AGENT_ID,
            tools=[code_interpreter]
        )
        print(f"Run created: {run.id}, status: {run.status}")

        # Poll for completion
        while run.status in ["queued", "in_progress", "requires_action"]:
            time.sleep(1)
            run = agents_client.runs.get(thread_id=thread_id, run_id=run.id)
            print(f"Run status: {run.status}")

        if run.status == "failed":
            raise Exception(run.last_error)

        # Get all messages from the thread
        messages = agents_client.messages.list(thread_id=thread_id)
        last_msg = None
        message_list = messages.data if hasattr(messages, 'data') else messages

        for msg_item in reversed(list(message_list)):
            if msg_item.role == "assistant":
                last_msg = msg_item
                break

        if not last_msg:
            raise Exception("No response from the model.")

        # Extract content
        content = ""
        if hasattr(last_msg, 'content') and last_msg.content:
            for content_item in last_msg.content:
                if hasattr(content_item, 'text') and hasattr(content_item.text, 'value'):
                    content = content_item.text.value
                    break
                elif hasattr(content_item, 'text'):
                    content = str(content_item.text)
                    break

        thinking_msg.content = content if content else "No response received"
        await thinking_msg.update()

    except Exception as e:
        await cl.Message(content=f"Error: {str(e)}").send()

if __name__ == "__main__":
    pass