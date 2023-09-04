from typing import Annotated

from fastapi import APIRouter, Header, WebSocket, WebSocketDisconnect
from langchain.llms import HuggingFaceTextGenInference
from langchain.memory import ConversationBufferWindowMemory
from langchain.sql_database import SQLDatabase
from loguru import logger

from sqlbot.agent import create_sql_agent, SQLBotToolkit
from sqlbot.callbacks import (
    UpdateConversationCallbackHandler,
    StreamingIntermediateThoughtCallbackHandler,
    StreamingFinalAnswerCallbackHandler,
)
from sqlbot.history import AppendSuffixHistory
from sqlbot.agent.prompts import (
    HUMAN_PREFIX,
    AI_PREFIX,
    HUMAN_SUFFIX,
    AI_SUFFIX,
)
from sqlbot.schemas import (
    ChatMessage,
    ConversationDetail,
    Conversation,
    UpdateConversation,
)
from sqlbot.config import settings
from sqlbot.utils import utcnow


router = APIRouter(
    prefix="/api",
    tags=["conversation"],
)


coder_llm = HuggingFaceTextGenInference(
    inference_server_url=settings.isvc_coder_llm,
    max_new_tokens=512,
    temperature=0.1,
    top_p=None,
    repetition_penalty=1.1,
    stop_sequences=["</s>"],
)
db = SQLDatabase.from_uri(settings.warehouse_url, sample_rows_in_table_info=3)


@router.get("/conversations", response_model=list[Conversation])
async def get_conversations(kubeflow_userid: Annotated[str | None, Header()] = None):
    convs = await Conversation.find(Conversation.owner == kubeflow_userid).all()
    convs.sort(key=lambda x: x.updated_at, reverse=True)
    return convs


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: str,
    kubeflow_userid: Annotated[str | None, Header()] = None,
):
    conv = await Conversation.get(conversation_id)
    history = AppendSuffixHistory(
        url=settings.redis_om_url,
        user_suffix=HUMAN_SUFFIX,
        ai_suffix=AI_SUFFIX,
        session_id=f"{kubeflow_userid}:{conversation_id}",
    )
    return ConversationDetail(
        messages=[
            ChatMessage(
                conversation=conversation_id,
                from_="ai",
                content=message.content,
                type="text",
            ).dict()
            if message.type == "ai"
            else ChatMessage(
                conversation=conversation_id,
                from_=kubeflow_userid,
                content=message.content,
                type="text",
            ).dict()
            for message in history.messages
        ],
        **conv.dict(),
    )


@router.post("/conversations", status_code=201, response_model=ConversationDetail)
async def create_conversation(kubeflow_userid: Annotated[str | None, Header()] = None):
    conv = Conversation(title=f"New chat", owner=kubeflow_userid)
    await conv.save()
    return conv


@router.put("/conversations/{conversation_id}")
async def update_conversation(
    conversation_id: str,
    payload: UpdateConversation,
    kubeflow_userid: Annotated[str | None, Header()] = None,
):
    conv = await Conversation.get(conversation_id)
    conv.title = payload.title
    conv.updated_at = utcnow()
    await conv.save()


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str, kubeflow_userid: Annotated[str | None, Header()] = None
):
    await Conversation.delete(conversation_id)


@router.websocket("/chat")
async def generate(
    websocket: WebSocket,
    kubeflow_userid: Annotated[str | None, Header()] = None,
):
    await websocket.accept()

    while True:
        try:
            payload: str = await websocket.receive_text()
            message = ChatMessage.parse_raw(payload)

            final_answer_stream_handler = StreamingFinalAnswerCallbackHandler(
                websocket, message.conversation
            )
            thought_stream_handler = StreamingIntermediateThoughtCallbackHandler(
                websocket, message.conversation
            )
            llm = HuggingFaceTextGenInference(
                inference_server_url=settings.isvc_llm,
                max_new_tokens=512,
                temperature=0.1,
                top_p=None,
                repetition_penalty=1.03,
                stop_sequences=["</s>", "Observation", "Thought"],
                callbacks=[thought_stream_handler, final_answer_stream_handler],
                streaming=True,
            )

            toolkit = SQLBotToolkit(
                db=db,
                llm=coder_llm,
                redis_url=settings.redis_om_url,
                websocket=websocket,
                conversation_id=message.conversation,
            )

            history = AppendSuffixHistory(
                url=settings.redis_om_url,
                user_suffix=HUMAN_SUFFIX,
                ai_suffix=AI_SUFFIX,
                session_id=f"{kubeflow_userid}:{message.conversation}",
            )
            memory = ConversationBufferWindowMemory(
                human_prefix=HUMAN_PREFIX,
                ai_prefix=AI_PREFIX,
                memory_key="history",
                chat_memory=history,
            )
            update_conversation_callback = UpdateConversationCallbackHandler(
                message.conversation
            )
            agent_executor = create_sql_agent(
                llm=llm,
                toolkit=toolkit,
                top_k=5,
                verbose=True,
                max_iterations=10,
                agent_executor_kwargs={
                    "memory": memory,
                    "callbacks": [update_conversation_callback],
                },
            )

            await agent_executor.arun(message.content)
        except WebSocketDisconnect:
            logger.info("websocket disconnected")
            return
        except Exception as e:
            logger.error(f"Something goes wrong, err: {e}")
