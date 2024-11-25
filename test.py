from computer_use_demo.loop import APIProvider, sampling_loop

# Setup
provider = APIProvider.BEDROCK
model = "anthropic.claude-3-5-sonnet-20241022-v2:0"

# Initialize conversation
messages = [
    {
        "role": "user",
        "content": [{"type": "text", "text": "Your message here"}]
    }
]

# Run the loop
sampling_loop(
    model=model,
    provider=provider,
    system_prompt_suffix="",
    messages=messages,
    output_callback=your_output_handler,
    tool_output_callback=your_tool_handler,
    api_response_callback=your_response_handler,
    api_key=""  # Not needed for Bedrock
)