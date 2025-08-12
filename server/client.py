import asyncio
from langchain_groq import ChatGroq
from dotenv import load_dotenv
from mcp_use import MCPClient, MCPAgent
import os 

async def run_memory_chat():
    """ Run a chat using MCP Agent's built-in memory."""
    load_dotenv()
    os.environ["GROQ_API_KEY"]=os.getenv("GROQ_API_KEY") # type: ignore

    #Config file path - change this to your config file
    config_file="server/weather.json"
    
    print("Initializing Chat")

    #Create MCP client and agent with memory enabled
    client=MCPClient.from_config_file(config_file)
    llm=ChatGroq(model="qwen-qwq-32b")

    #Create mcp agent with memory enabled
    agent=MCPAgent(client=client,llm=llm,max_steps=15,memory_enabled=True)

    print("\n==== Interactive MCP Chat ====")
    print("Type 'exit' or 'quit' to end the conversation")
    print("Type 'clear' to clear the conversation history")
    print("================================")

    try:
        #Main chat loop
        while True:
            #Get user input
            user_input=input("You: ")

            #Check for exit commands
            if user_input.lower() in ["exit","quit"]:
                print("Ending chat")
                break
            
            if user_input.lower() == "clear":
                agent.clear_conversation_history()
                print("Conversation history cleared")
                continue

            #Get response from agent
            print("\n Assistant: ",end="",flush=True)

            try:
                # Run agent with user input (memory handling is automatic)
                response=await agent.run(user_input)
                print(response)

            except Exception as e:
                print(f"\nError: {e}")
    finally:
        if client and client.sessions:
            await client.close_all_sessions()

if __name__=="__main__":
    asyncio.run(run_memory_chat())



