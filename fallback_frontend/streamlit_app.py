import streamlit as st
import asyncio
import os
import base64
from computer_use_demo.loop import sampling_loop, APIProvider
from computer_use_demo.tools import ToolResult
from anthropic.types.beta import BetaMessageParam, BetaMessage
from anthropic import APIResponse
import json
from io import BytesIO
from PIL import Image

st.set_page_config(page_title="Claude Computer Use Demo", layout="wide")

st.title("Claude Computer Use Demo")

# Sidebar for configuration
with st.sidebar:
    st.header("Configuration")
    model = st.selectbox(
        "Model",
        ["anthropic.claude-3-5-sonnet-20241022-v2:0"],
        index=0
    )
    provider = st.selectbox(
        "Provider",
        [APIProvider.BEDROCK],
        index=0
    )
    system_prompt = st.text_area(
        "System Prompt Suffix",
        value="This is a mac device",
        height=100
    )
    max_tokens = st.number_input(
        "Max Tokens",
        min_value=1,
        max_value=4096,
        value=4096
    )

# Main content area
col1, col2 = st.columns([2, 1])

with col1:
    instruction = st.text_input("Enter your instruction:", "What do you see in this screenshot?")

with col2:
    uploaded_file = st.file_uploader("Upload a screenshot", type=['png', 'jpg', 'jpeg'])
    if uploaded_file is not None:
        image = Image.open(uploaded_file)
        st.image(image, caption="Uploaded Screenshot", use_container_width=True)

# Create containers for different types of output
text_output = st.empty()
tool_output = st.empty()
screenshots_container = st.container()

if 'messages' not in st.session_state:
    st.session_state.messages = []
    st.session_state.screenshots = []

def encode_image_to_base64(image):
    buffered = BytesIO()
    image.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode()

async def run_computer_use():
    # Prepare the initial message with image if provided
    if uploaded_file is not None:
        image_base64 = encode_image_to_base64(image)
        messages: list[BetaMessageParam] = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_base64
                        }
                    },
                    {
                        "type": "text",
                        "text": instruction
                    }
                ]
            }
        ]
    else:
        messages: list[BetaMessageParam] = [
            {
                "role": "user",
                "content": instruction,
            }
        ]

    def output_callback(content_block):
        if isinstance(content_block, dict) and content_block.get("type") == "text":
            text_output.write(f"Assistant: {content_block.get('text')}")
            st.session_state.messages.append(("assistant", content_block.get("text")))

    def tool_output_callback(result: ToolResult, tool_use_id: str):
        if result.output:
            tool_output.write(f"> Tool Output [{tool_use_id}]: {result.output}")
        if result.error:
            tool_output.write(f"!!! Tool Error [{tool_use_id}]: {result.error}")
        if result.base64_image:
            st.session_state.screenshots.append(
                (f"screenshot_{tool_use_id}.png", result.base64_image)
            )

    def api_response_callback(response: APIResponse[BetaMessage]):
        st.session_state.messages.append(
            ("system", json.dumps(json.loads(response.text)["content"], indent=4))
        )

    try:
        messages = await sampling_loop(
            model=model,
            provider=provider,
            system_prompt_suffix=system_prompt,
            messages=messages,
            output_callback=output_callback,
            tool_output_callback=tool_output_callback,
            api_response_callback=api_response_callback,
            api_key="",
            only_n_most_recent_images=10,
            max_tokens=max_tokens,
        )
    except Exception as e:
        st.error(f"Error occurred: {str(e)}")

# Clear button to reset the conversation
if st.button("Clear Conversation"):
    st.session_state.messages = []
    st.session_state.screenshots = []
    st.rerun()

if st.button("Run"):
    asyncio.run(run_computer_use())

# Display conversation history
st.subheader("Conversation History")
for role, message in st.session_state.messages:
    if role == "assistant":
        st.write(f"🤖 Assistant: {message}")
    elif role == "system":
        with st.expander("Show API Response"):
            st.code(message, language="json")

# Display screenshots
if st.session_state.screenshots:
    st.subheader("Screenshots")
    cols = st.columns(3)
    for idx, (filename, base64_image) in enumerate(st.session_state.screenshots):
        col = cols[idx % 3]
        image_data = base64.b64decode(base64_image)
        col.image(image_data, caption=filename)
        
        # Add download button for each image
        buf = BytesIO(image_data)
        col.download_button(
            label=f"Download {filename}",
            data=buf,
            file_name=filename,
            mime="image/png"
        )