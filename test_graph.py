from graph.graph import graph

print("START")

for chunk in graph.stream(
    {
        "raw_message": "debug KeyError: user_id",
        "user_id": "test-user"
    }
):
    print("CHUNK")
    print(chunk)

print("END")
