import os
import chainlit as cl
import logging
import time
from dotenv import load_dotenv
from azure.ai.projects import AIProjectClient
from azure.identity import InteractiveBrowserCredential
from azure.ai.agents.models import CodeInterpreterTool

# Load environment variables
load_dotenv()

# Disable verbose connection logs
logger = logging.getLogger("azure.core.pipeline.policies.http_logging_policy")
logger.setLevel(logging.WARNING)

AGENT_ID = "asst_HkPiz9n1tnB9VHJ7YckpGW76"

# Create an instance of the AIProjectClient using InteractiveBrowserCredential
credential = InteractiveBrowserCredential()

# Method 1: Using Connection String (RECOMMENDED)
PROJECT_CONNECTION_STRING = os.getenv("AIPROJECT_CONNECTION_STRING")

print("=== Project Configuration ===")
print(f"Connection String: {PROJECT_CONNECTION_STRING}")
print(f"Agent ID: {AGENT_ID}")

# Create an instance of the AIProjectClient using connection string
try:
    if PROJECT_CONNECTION_STRING:
        project_client = AIProjectClient.from_connection_string(
            conn_str=PROJECT_CONNECTION_STRING,
            credential=credential
        )
        print("✅ Project client created successfully using connection string")
    else:
        raise Exception("PROJECT_CONNECTION_STRING not found in environment variables")
        
except Exception as e:
    print(f"❌ Failed to create project client: {e}")
    print("Please add PROJECT_CONNECTION_STRING to your .env file")
    exit(1)

# Test connection
async def test_connection():
    try:
        # Try to list agents to test connection
        agents = project_client.agents.list_agents()
        agent_count = len(agents.data) if hasattr(agents, 'data') else 0
        print(f"✅ Connection successful. Found {agent_count} agents")
        
        # List available agents for debugging
        if agent_count > 0:
            print("Available agents:")
            for agent in agents.data:
                print(f"  - ID: {agent.id}, Name: {getattr(agent, 'name', 'Unnamed')}")
        
        return True
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False

# Chainlit setup
@cl.on_chat_start
async def on_chat_start():
    print("=== Chat started ===")
    
    # Test connection first
    if not await test_connection():
        await cl.Message("❌ Unable to connect to Azure AI Project. Please check your configuration.").send()
        return
    
    # Create thread at start using connection string client
    try:
        # Create a thread for the agent with code interpreter tool
        code_interpreter = CodeInterpreterTool()
        thread = project_client.agents.create_thread()
        cl.user_session.set("thread_id", thread.id)
        cl.user_session.set("code_interpreter", code_interpreter)
        logger.warning(f"New thread created with code interpreter, thread ID: {thread.id}")
        
        print(f"Thread created: {thread.id}")
        await cl.Message("✅ Connected to Azure AI Project successfully!").send()
        
    except Exception as e:
        print(f"Thread creation failed: {e}")
        await cl.Message(f"❌ Thread creation failed: {e}").send()

@cl.on_message
async def on_message(message: cl.Message):
    thread_id = cl.user_session.get("thread_id")
    print(f"=== Processing message for thread: {thread_id} ===")

    try:
        # Show thinking message to user
        msg = await cl.Message("thinking...", author="agent").send()

        if not thread_id:
            # If no thread exists, create one
            thread = project_client.agents.create_thread()
            thread_id = thread.id
            cl.user_session.set("thread_id", thread_id)
            print(f"New thread created: {thread_id}")

        # Add message to thread
        project_client.agents.create_message(
            thread_id=thread_id,
            role="user",
            content=message.content
        )
        print("Message added to thread")

        # Create and execute run
        run = project_client.agents.create_run(
            thread_id=thread_id,
            assistant_id=AGENT_ID
        )
        print(f"Run created: {run.id}, status: {run.status}")

        # Poll for completion
        print(f"Initial run status: {run.status}")
        while run.status in ["queued", "in_progress", "requires_action"]:
            time.sleep(1)
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