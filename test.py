import os
import chainlit as cl
import logging
import time
from dotenv import load_dotenv
from azure.ai.projects import AIProjectClient
from azure.identity import InteractiveBrowserCredential

# Load environment variables
load_dotenv()

# Disable verbose connection logs
logger = logging.getLogger("azure.core.pipeline.policies.http_logging_policy")
logger.setLevel(logging.WARNING)

AGENT_ID = "asst_HkPiz9n1tnB9VHJ7YckpGW76"

# Create an instance of the AIProjectClient using InteractiveBrowserCredential
credential = InteractiveBrowserCredential()

# Create an instance of the AIProjectClient
project_client = AIProjectClient(
    endpoint="https://swedencentral.api.azureml.ms",
    credential=credential,
    subscription_id=os.getenv("AZURE_SUBSCRIPTION_ID"),
    resource_group_name=os.getenv("AZURE_RESOURCE_GROUP"), 
    project_name=os.getenv("AZURE_PROJECT_NAME")
)

# Chainlit setup
@cl.on_chat_start
async def on_chat_start():
    print("=== Chat started ===")
    
    # Create thread at start (new recommended pattern)
    try:
        thread = project_client.agents.threads.create()
        cl.user_session.set("thread_id", thread.id)
        print(f"Thread created: {thread.id}")
    except AttributeError:
        # Fallback if threads sub-client doesn't exist
        try:
            thread = project_client.agents.create_thread()
            cl.user_session.set("thread_id", thread.id)
            print(f"Thread created (fallback): {thread.id}")
        except Exception as e:
            print(f"Thread creation failed: {e}")

@cl.on_message
async def on_message(message: cl.Message):
    thread_id = cl.user_session.get("thread_id")
    print(f"=== Processing message for thread: {thread_id} ===")

    try:
        # Show thinking message to user
        msg = await cl.Message("thinking...", author="agent").send()

        if not thread_id:
            # If no thread exists, create one
            try:
                thread = project_client.agents.threads.create()
                thread_id = thread.id
                cl.user_session.set("thread_id", thread_id)
                print(f"New thread created: {thread_id}")
            except AttributeError:
                thread = project_client.agents.create_thread()
                thread_id = thread.id
                cl.user_session.set("thread_id", thread_id)
                print(f"New thread created (fallback): {thread_id}")

        # Add message to thread
        try:
            # Method 1: Using sub-client (new pattern)
            project_client.agents.messages.create(
                thread_id=thread_id,
                role="user",
                content=message.content
            )
            print("Message added using sub-client")
        except AttributeError:
            # Method 2: Direct client (fallback)
            project_client.agents.create_message(
                thread_id=thread_id,
                role="user",
                content=message.content
            )
            print("Message added using direct client")

        # Create and execute run
        try:
            # Method 1: Using sub-client (new pattern)
            run = project_client.agents.runs.create(
                thread_id=thread_id,
                assistant_id=AGENT_ID
            )
            print("Run created using sub-client")
        except AttributeError:
            # Method 2: Direct client (fallback)
            run = project_client.agents.create_run(
                thread_id=thread_id,
                assistant_id=AGENT_ID
            )
            print("Run created using direct client")

        # Poll for completion
        print(f"Initial run status: {run.status}")
        while run.status in ["queued", "in_progress", "requires_action"]:
            time.sleep(1)
            try:
                # Method 1: Using sub-client
                run = project_client.agents.runs.retrieve(
                    thread_id=thread_id,
                    run_id=run.id
                )
            except AttributeError:
                # Method 2: Direct client
                run = project_client.agents.get_run(
                    thread_id=thread_id,
                    run_id=run.id
                )
            print(f"Run status: {run.status}")

        print(f"Run finished with status: {run.status}")

        # Check if run failed
        if run.status == "failed":
            error_msg = run.last_error.message if hasattr(run, 'last_error') and run.last_error else "Unknown error"
            raise Exception(f"Run failed: {error_msg}")

        # Get messages from the thread
        try:
            # Method 1: Using sub-client
            messages = project_client.agents.messages.list(thread_id=thread_id)
        except AttributeError:
            # Method 2: Direct client
            messages = project_client.agents.list_messages(thread_id=thread_id)

        # Find the last assistant message
        last_msg = None
        message_list = messages.data if hasattr(messages, 'data') else messages

        # Sort by created_at to get the latest message
        if hasattr(message_list, '__iter__'):
            sorted_messages = sorted(message_list, key=lambda x: getattr(x, 'created_at', 0), reverse=True)
            for msg_item in sorted_messages:
                if msg_item.role == "assistant":
                    last_msg = msg_item
                    break

        if not last_msg:
            raise Exception("No response from the model.")

        # Extract text content from the message
        content = ""
        if hasattr(last_msg, 'content') and last_msg.content:
            for content_item in last_msg.content:
                if hasattr(content_item, 'text') and hasattr(content_item.text, 'value'):
                    content = content_item.text.value
                    break
                elif hasattr(content_item, 'text') and isinstance(content_item.text, str):
                    content = content_item.text
                    break

        if not content:
            raise Exception("No text content in the response.")

        msg.content = content
        await msg.update()

    except Exception as e:
        print(f"Error details: {e}")
        await cl.Message(content=f"Error: {str(e)}").send()

if __name__ == "__main__":
    pass