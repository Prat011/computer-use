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
import nest_asyncio
import signal

# Apply nest_asyncio to allow nested event loops
nest_asyncio.apply()

def load_instructions():
    """Load instructions from instructions.txt file"""
    try:
        with open('instructions.txt', 'r') as file:
            instructions = [line.strip() for line in file.readlines() if line.strip()]
            instructions = [instr[2:] if instr.startswith('- ') else instr for instr in instructions]
            return instructions
    except FileNotFoundError:
        default_instructions = [
            "What operating system is this?",
            "Open the calculator app",
            "What is 2+2?"
        ]
        save_instructions(default_instructions)
        return default_instructions

def save_instructions(instructions):
    """Save instructions to instructions.txt file"""
    with open('instructions.txt', 'w') as file:
        for instruction in instructions:
            file.write(f"- {instruction}\n")
        
# Initialize Streamlit state for task tracking
if 'initialized' not in st.session_state:
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    st.session_state.initialized = True
    st.session_state.messages = []
    st.session_state.screenshots = []
    st.session_state.loop = loop
    st.session_state.instructions = load_instructions()
    st.session_state.current_task = None
    st.session_state.is_running = False
    st.session_state.current_step = 0
    st.session_state.step_completed = False

def init_asyncio_loop():
    return st.session_state.loop

# Initialize the asyncio loop
loop = init_asyncio_loop()

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

    # Add instructions editor in sidebar
    st.header("Edit Instructions")
    instructions_text = "\n".join(f"- {instr}" for instr in st.session_state.instructions)
    edited_instructions = st.text_area(
        "Instructions (one per line, start with '-')",
        value=instructions_text,
        height=200
    )
    if st.button("Save Instructions"):
        new_instructions = [line.strip()[2:] if line.strip().startswith('- ') else line.strip() 
                          for line in edited_instructions.split('\n') 
                          if line.strip()]
        save_instructions(new_instructions)
        st.session_state.instructions = new_instructions
        st.session_state.current_step = 0
        st.session_state.step_completed = False
        st.success("Instructions saved!")

# Main content area
st.subheader("Current Instruction")
if st.session_state.instructions:
    # Add bounds checking
    if st.session_state.current_step >= len(st.session_state.instructions):
        st.session_state.current_step = len(st.session_state.instructions) - 1
    current_instruction = st.session_state.instructions[st.session_state.current_step]
    st.info(f"Step {st.session_state.current_step + 1} of {len(st.session_state.instructions)}: {current_instruction}")
else:
    st.warning("No instructions available. Please add some in the sidebar.")

col1, col2 = st.columns([2, 1])

with col2:
    st.write("📸 Click a screenshot to continue")
    uploaded_file = st.file_uploader("Upload a screenshot", type=['png', 'jpg', 'jpeg'])
    if uploaded_file is not None:
        image = Image.open(uploaded_file)
        st.image(image, caption="Uploaded Screenshot", use_container_width=True)

# Create containers for different types of output
text_output = st.empty()
tool_output = st.empty()
screenshots_container = st.container()

def encode_image_to_base64(image):
    buffered = BytesIO()
    image.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode()

async def run_computer_use():
    try:
        st.session_state.is_running = True
        current_instruction = st.session_state.instructions[st.session_state.current_step]
        
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
                            "text": f"Click a screenshot. {current_instruction}"
                        }
                    ]
                }
            ]
        else:
            messages: list[BetaMessageParam] = [
                {
                    "role": "user",
                    "content": f"Click a screenshot. {current_instruction}",
                }
            ]

        def output_callback(content_block):
            if isinstance(content_block, dict) and content_block.get("type") == "text":
                text_output.write(f"Assistant: {content_block.get('text')}")
                st.session_state.messages.append(("assistant", content_block.get("text")))

        def tool_output_callback(result: ToolResult, tool_use_id: str):
            if result.output:
                tool_output.write(f"> Tool Output [{tool_use_id}]: {result.output}")
                st.session_state.messages.append(("tool", f"Tool Output: {result.output}"))
            if result.error:
                tool_output.write(f"!!! Tool Error [{tool_use_id}]: {result.error}")
                st.session_state.messages.append(("error", f"Error: {result.error}"))
            if result.base64_image:
                st.session_state.screenshots.append(
                    (f"screenshot_{tool_use_id}.png", result.base64_image)
                )

        def api_response_callback(response: APIResponse[BetaMessage]):
            # We'll now only store the actual message content, not the full API response
            content = json.loads(response.text)["content"]
            if isinstance(content, list):
                for item in content:
                    if item.get("type") == "text":
                        st.session_state.messages.append(("system", item.get("text")))
            elif isinstance(content, dict) and content.get("type") == "text":
                st.session_state.messages.append(("system", content.get("text")))

        try:
            await sampling_loop(
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
            st.session_state.step_completed = True
            
        except asyncio.CancelledError:
            st.warning("Execution was stopped by user")
            raise
        except Exception as e:
            st.error(f"Error occurred: {str(e)}")
            raise
        finally:
            st.session_state.is_running = False
            st.session_state.current_task = None
    
    except Exception as e:
        st.error(f"Error occurred: {str(e)}")
        st.session_state.is_running = False
        st.session_state.current_task = None

async def execute_all_remaining_steps():
    while (st.session_state.current_step < len(st.session_state.instructions) and 
           not st.session_state.is_running):
        await run_computer_use()
        if st.session_state.step_completed:
            st.session_state.current_step += 1
            st.session_state.step_completed = False
        else:
            break

def run_async_code():
    loop = st.session_state.loop
    task = asyncio.ensure_future(execute_all_remaining_steps(), loop=loop)
    st.session_state.current_task = task
    try:
        loop.run_until_complete(task)
    except asyncio.CancelledError:
        st.warning("Execution stopped")
    except Exception as e:
        st.error(f"Error occurred: {str(e)}")
    finally:
        st.session_state.is_running = False
        st.session_state.current_task = None

# Create columns for the control buttons
col1, col2, col3, col4 = st.columns(4)

with col1:
    if st.button("Execute All Steps", disabled=st.session_state.is_running or not st.session_state.instructions):
        run_async_code()

with col2:
    if st.button("Next Step", disabled=not st.session_state.step_completed or 
                 st.session_state.current_step >= len(st.session_state.instructions) - 1):
        st.session_state.current_step += 1
        st.session_state.step_completed = False
        st.rerun()

with col3:
    if st.button("Stop", disabled=not st.session_state.is_running):
        if st.session_state.current_task:
            st.session_state.current_task.cancel()

with col4:
    if st.button("Clear Conversation"):
        st.session_state.messages = []
        st.session_state.current_step = 0
        st.session_state.step_completed = False
        st.session_state.is_running = False
        st.session_state.current_task = None
        st.rerun()

# Reset button
if st.button("Reset All", disabled=st.session_state.is_running):
    st.session_state.messages = []
    st.session_state.screenshots = []
    st.session_state.current_step = 0
    st.session_state.step_completed = False
    st.rerun()

# Display conversation history
st.subheader("Conversation History")
for role, message in st.session_state.messages:
    if role == "assistant":
        st.write(f"🤖 Assistant: {message}")
    elif role == "system":
        st.write(f"💻 System: {message}")
    elif role == "tool":
        st.write(f"🔧 {message}")
    elif role == "error":
        st.write(f"❌ {message}")

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

# Clean up the loop when the script exits
import atexit

def cleanup():
    if st.session_state.loop:
        st.session_state.loop.close()

atexit.register(cleanup)