from flow_agent.app.bootstrap import create_agent

def main() -> None:
    agent = create_agent()
    print("Flow Agent CLI")
    print("Enter 'exit' to quit")

    while True:
        user_input=input("You: ")
        if user_input.lower() == "exit":
            break
        response = agent.run(user_input)
        print(f"Agent: {response.content}")


if __name__ == "__main__":
    main()
