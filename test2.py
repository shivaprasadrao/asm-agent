import os
import time
import logging
import chainlit as cl
from loguru import logger
from typing import Dict, Optional
from dotenv import load_dotenv
from azure.ai.agents import AgentsClient
from azure.ai.projects import AIProjectClient
from azure.identity import InteractiveBrowserCredential
from azure.ai.agents.models import CodeInterpreterTool
from utils.utils import append_message, init_settings, get_llm_details, get_llm_models
from utils.chats import chat_completion
from utils.foundry import chat_agent

# Load environment variables from sample.env
load_dotenv("sample.env")

# Disable verbose connection logs
logger = logging.getLogger("azure.core.pipeline.policies.http_logging_policy")
logger.setLevel(logging.WARNING)

# Environment variables
AIPROJECT_CONNECTION_STRING = os.getenv("AIPROJECT_CONNECTION_STRING")
AGENT_ID = os.getenv("AGENT_ID")

@cl.header_auth_callback
def header_auth_callback(headers: Dict) -> Optional[cl.User]:
    # Verify the signature of a token in the header (ex: jwt token)
    # or check that the value is matching a row from your database
    user_name = headers.get('X-MS-CLIENT-PRINCIPAL-NAME', 'dummy@microsoft.com')
    user_id = headers.get('X-MS-CLIENT-PRINCIPAL-ID', '9876543210')
    print(f">>>>> Headers: {headers}")

    if user_name:
        return cl.User(identifier=user_name, metadata={"role": "admin", "provider": "header", "id": user_id})
    else:
        return None


@cl.set_chat_profiles
async def chat_profile():
    llm_models = get_llm_models()
    # get a list of model names from llm_models
    model_list = [f"{model["model_deployment"]}--{model["description"]}" for model in llm_models]
    profiles = []

    for item in model_list:
        model_deployment, description = item.split("--")

        # Create a profile for each model
        profiles.append(
            cl.ChatProfile(
                name=model_deployment,
                markdown_description=description
            )
        )

    return profiles


@cl.set_starters
async def set_starters():
    return [
        cl.Starter(
            label="Morning routine ideation",
            message="Can you help me create a personalized morning routine that would help increase my productivity throughout the day? Start by asking me about my current habits and what activities energize me in the morning.",
            icon="/public/bulb.webp",
            ),

        cl.Starter(
            label="Spot the errors",
            message="How can I avoid common mistakes when proofreading my work?",
            icon="/public/warning.webp",
            ),
        cl.Starter(
            label="Get more done",
            message="How can I improve my productivity during remote work?",
            icon="/public/rocket.png",
            ),
        cl.Starter(
            label="Boost your knowledge",
            message="Help me learn about [topic]",
            icon="/public/book.png",
            )
        ]


@cl.on_chat_resume
async def on_chat_resume(thread):
    pass


@cl.on_chat_start
async def start():
    """
    Initialize the chat session and send a welcome message.
    """
    try:
        cl.user_session.set("chat_settings", await init_settings())
        llm_details = get_llm_details()
        
        # Create an instance of the AIProjectClient using InteractiveBrowserCredential
        if cl.user_session.get("chat_settings").get("model_provider") == "foundry" and not cl.user_session.get("thread_id"):
            
            # Create InteractiveBrowserCredential for authentication
            credential = InteractiveBrowserCredential()
            
            # Create agents client using endpoint and credential
            if llm_details.get("api_endpoint"):
                agents_client = AgentsClient(
                    endpoint=llm_details["api_endpoint"],
                    credential=credential
                )
            else:
                # Fallback to AIProjectClient if endpoint not available
                project_client = AIProjectClient.from_connection_string(
                    conn_str=AIPROJECT_CONNECTION_STRING,
                    credential=credential
                )
                agents_client = project_client.agents

            # Store the agents client in session
            cl.user_session.set("agents_client", agents_client)
            
            # Create a thread for the agent with code interpreter tool
            code_interpreter = CodeInterpreterTool()
            thread = agents_client.threads.create()
            
            cl.user_session.set("thread_id", thread.id)
            cl.user_session.set("code_interpreter", code_interpreter)
            logger.warning(f"New thread created with code interpreter, thread ID: {thread.id}")

        await cl.Message("✅ Connected successfully! Ready to assist you with code interpretation and analysis.", author="System").send()

    except Exception as e:
        await cl.Message(content=f"An error occurred during initialization: {str(e)}", author="Error").send()
        logger.error(f"Initialization error: {str(e)}")


@cl.on_message
async def main(message: cl.Message):
    """
    Process incoming user messages and generate responses using Azure AI Agents.
    
    Args:
        message: The message object from Chainlit containing user's input
    """
    try:
        cl.user_session.set("start_time", time.time())
        user_input = message.content
        thread_id = cl.user_session.get("thread_id")
        agents_client = cl.user_session.get("agents_client")

        # Show thinking message to user
        thinking_msg = await cl.Message("thinking...", author="agent").send()

        if cl.user_session.get("chat_settings").get("model_provider") == "foundry":
            
            # If we have thread_id and agents_client, use direct agent interaction
            if thread_id and agents_client:
                
                # Add user message to the thread
                agents_client.messages.create(
                    thread_id=thread_id,
                    role="user",
                    content=user_input
                )
                
                # Create and run the agent with code interpreter tool
                run = agents_client.runs.create(
                    thread_id=thread_id,
                    assistant_id=AGENT_ID,
                    tools=[cl.user_session.get("code_interpreter")] if cl.user_session.get("code_interpreter") else None
                )
                
                # Poll for completion
                while run.status in ["queued", "in_progress", "requires_action"]:
                    time.sleep(1)
                    run = agents_client.runs.retrieve(thread_id=thread_id, run_id=run.id)
                    
                    # Handle tool calls if needed
                    if run.status == "requires_action":
                        # Handle code interpreter or other tool calls here
                        # This would involve processing tool outputs and submitting them back
                        pass
                
                if run.status == "failed":
                    raise Exception(f"Run failed: {run.last_error}")
                
                # Get messages from the thread
                messages = agents_client.messages.list(thread_id=thread_id)
                
                # Find the last assistant message
                last_msg = None
                for msg_item in messages.data:
                    if msg_item.role == "assistant":
                        last_msg = msg_item
                        break
                
                if not last_msg:
                    raise Exception("No response from the agent.")
                
                # Extract text content
                content = ""
                if hasattr(last_msg, 'content') and last_msg.content:
                    for content_item in last_msg.content:
                        if hasattr(content_item, 'text') and hasattr(content_item.text, 'value'):
                            content = content_item.text.value
                            break
                
                if not content:
                    raise Exception("No text content in the response.")
                
                full_response = content
            else:
                # Fallback to utils function
                full_response = await chat_agent(user_input)
        else:
            # Get messages from session for non-foundry providers
            messages = append_message("user", user_input, message.elements)
            full_response = await chat_completion(messages)

        # Update the thinking message with the response
        thinking_msg.content = full_response
        await thinking_msg.update()

        # Save the complete message to session
        append_message("assistant", full_response)

    except Exception as e:
        await cl.Message(content=f"An error occurred: {str(e)}", author="Error").send()
        logger.error(f"Error: {str(e)}")


if __name__ == "__main__":
    pass