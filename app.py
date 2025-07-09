import os
import chainlit as cl
from dotenv import load_dotenv
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.agents.models import ListSortOrder

# Load environment variables if needed
load_dotenv()

PROJECT_ENDPOINT = os.getenv("PROJECT_ENDPOINT")  
AGENT_ID = os.getenv("AGENT_ID")  

project = AIProjectClient(
    credential=DefaultAzureCredential(),
    endpoint=PROJECT_ENDPOINT
)

agent = project.agents.get_agent(AGENT_ID)

@cl.on_chat_start
async def on_chat_start():
    thread = project.agents.threads.create()
    cl.user_session.set("thread_id", thread.id)
    print(f"Created thread, ID: {thread.id}")

@cl.on_message
async def on_message(message: cl.Message):
    thread_id = cl.user_session.get("thread_id")
    try:
        # Show "thinking..." message
        thinking_msg = await cl.Message("thinking...", author="agent").send()

        # Add user message to the thread
        project.agents.messages.create(
            thread_id=thread_id,
            role="user",
            content=message.content
        )

        # Run the agent and wait for completion
        run = project.agents.runs.create_and_process(
            thread_id=thread_id,
            agent_id=agent.id
        )

        if run.status == "failed":
            await cl.Message(content=f"Run failed: {run.last_error}").send()
            return

        # Get all messages in the thread
        messages = project.agents.messages.list(thread_id=thread_id, order=ListSortOrder.ASCENDING)

        # Find the last assistant message with text
        last_response = ""
        for msg in reversed(list(messages)):
            if msg.role == "assistant" and getattr(msg, "text_messages", None):
                last_response = msg.text_messages[-1].text.value
                break

        thinking_msg.content = last_response if last_response else "No response from the model."
        await thinking_msg.update()

    except Exception as e:
        await cl.Message(content=f"Error: {str(e)}").send()