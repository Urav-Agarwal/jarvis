from ai.plan_parser import PlanParser


parser = PlanParser()


def expect_rejection(name, data):
    try:
        parser.parse(data)
        print(f"FAIL: {name} was accepted")
    except ValueError as error:
        print(f"PASS: {name} -> {error}")


expect_rejection(
    "wrong type",
    {
        "type": "wrong",
        "actions": [],
    },
)

expect_rejection(
    "actions not a list",
    {
        "type": "plan",
        "actions": "not a list",
    },
)

expect_rejection(
    "missing tool",
    {
        "type": "plan",
        "actions": [
            {
                "parameters": {},
            }
        ],
    },
)

expect_rejection(
    "future dependency",
    {
        "type": "plan",
        "actions": [
            {
                "tool": "system.volume",
                "parameters": {},
                "depends_on": [1],
            }
        ],
    },
)