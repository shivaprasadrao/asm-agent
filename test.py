import os
import chainlit as cl
import logging
from dotenv import load_dotenv
from azure.ai.projects import AIProjectClient
#from azure.identity import InteractiveBrowserCredential
from azure.identity import DefaultAzureCredential
from azure.ai.agents.models import CodeInterpreterTool

# Load environment variables
load_dotenv("sample.env")

logger = logging.getLogger("azure.core.pipeline.policies.http_logging_policy")
logger.setLevel(logging.WARNING)

AIPROJECT_CONNECTION_STRING = os.getenv("AIPROJECT_CONNECTION_STRING")
AGENT_ID = os.getenv("AGENT_ID")
subscription_id = os.getenv("AZURE_SUBSCRIPTION_ID")
resource_group_name = os.getenv("AZURE_RESOURCE_GROUP")
project_name = os.getenv("AZURE_PROJECT_NAME")
#credential = DefaultAzureCredential()  # Use DefaultAzureCredential for local development and production
#InteractiveBrowserCredential()

# Print loaded environment variables for debugging
print("Loaded AGENT_ID:", os.getenv("AGENT_ID"))
print("Loaded AIPROJECT_CONNECTION_STRING:", os.getenv("AIPROJECT_CONNECTION_STRING"))
print("AIPROJECT_CONNECTION_STRING repr:", repr(AIPROJECT_CONNECTION_STRING))
print("Loaded subscription_id:", subscription_id)
print("Loaded resource_group_name:", resource_group_name)
print("Loaded project_name:", project_name)

# Create an instance of the AIProjectClient using connection string

project_client = AIProjectClient(
    endpoint=AIPROJECT_CONNECTION_STRING,
    credential=DefaultAzureCredential(),
    subscription_id=subscription_id,
    resource_group_name=resource_group_name,
    project_name=project_name
)

code_interpreter = CodeInterpreterTool()

# Chainlit setup
@cl.on_chat_start
async def on_chat_start():
    # Create a thread for the agent using the correct method for your SDK version
    if not cl.user_session.get("thread_id"):
        thread = project_client.agents.create_thread()
        cl.user_session.set("thread_id", thread.id)
        print(f"New Thread ID: {thread.id}")

@cl.on_message
async def on_message(message: cl.Message):
    thread_id = cl.user_session.get("thread_id")
    
    try:
        # Show thinking message to user
        msg = await cl.Message("thinking...", author="agent").send()

        # Add user message to the thread using the messages sub-client
        project_client.agents.messages.create(
            thread_id=thread_id,
            role="user",
            content=message.content,
        )

        # Create and run the agent using the runs sub-client
        run = project_client.agents.runs.create(
            thread_id=thread_id,
            assistant_id=AGENT_ID,
            tools=[code_interpreter]
        )
        print(f"Run created: {run.id}, status: {run.status}")

        # Poll for completion
        while run.status in ["queued", "in_progress", "requires_action"]:
            import time
            time.sleep(1)
            run = project_client.agents.runs.retrieve(thread_id=thread_id, run_id=run.id)
            print(f"Run status: {run.status}")

        if run.status == "failed":
            raise Exception(run.last_error)

        # Get all messages from the thread using the messages sub-client
        messages = project_client.agents.messages.list(thread_id=thread_id)
        last_msg = None
        message_list = messages.data if hasattr(messages, 'data') else messages

        for msg_item in message_list:
            if msg_item.role == "assistant":
                last_msg = msg_item
                break

        if not last_msg:
            raise Exception("No response from the model.")

        msg.content = last_msg.text.value
        await msg.update()

    except Exception as e:
        await cl.Message(content=f"Error: {str(e)}").send()

if __name__ == "__main__":
    # Chainlit will automatically run the application
    pass