import "./index.css";

import ReactMarkdown from "react-markdown";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import remarkGfm from "remark-gfm";
import { darcula } from "react-syntax-highlighter/dist/esm/styles/prism";

import Avatar from "@mui/material/Avatar";
import Tooltip from "@mui/material/Tooltip";
import VisibilityOutlinedIcon from '@mui/icons-material/VisibilityOutlined';

import { getFirstLetters, stringToColor } from "commons";


/**
 * Checks whether a message is sent by bot.
 * @param {*} message
 */
const botMessage = (message) => {
  const msgFrom = message.from.toLowerCase();
  return msgFrom === "ai" || msgFrom === "assistant";
};

/**
 *
 * @param {object} props
 * @param {object} props.message
 * @param {string} props.message.from
 * @param {string} props.message.content
 * @param {string} props.onStepsClick
 * @returns
 */
const ChatMessage = (props) => {
  return (
    <div className={`chat-message ${botMessage(props.message) && "AI"}`}>
      <div className="chat-message-center">
        <Avatar
          className="chat-message-avatar"
          // Cannot handle string to color in css
          sx={{
            bgcolor: stringToColor(props.message.from),
          }}
        >
          {botMessage(props.message)
            ? "AI"
            : getFirstLetters(props.message.from)}
        </Avatar>
        <ReactMarkdown
          className="chat-message-content"
          children={props.message.content}
          // remarkPlugins={[remarkGfm]}
          components={{
            code({ node, inline, className, children, ...props }) {
              const match = /language-(\w+)/.exec(className || "");
              return !inline && match ? (
                <SyntaxHighlighter
                  {...props}
                  children={String(children).replace(/\n$/, "")}
                  style={darcula}
                  language={match[1]}
                  PreTag="div"
                />
              ) : (
                <code {...props} className={className}>
                  {children}
                </code>
              );
            },
          }}
        />
        {props.message.intermediate_steps && (
          <Tooltip title="show intermediate steps">
            <VisibilityOutlinedIcon
              className="show-steps-icon"
              onClick={props.onStepsClick}
            />
          </Tooltip>
        )}
      </div>
    </div>
  );
};

export default ChatMessage;
