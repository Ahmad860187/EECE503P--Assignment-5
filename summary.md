# Part 1: MCP and the filesystem server

The article (Ksenia Se, on Hugging Face and Turing Post) starts from a simple problem. LLMs are smart, but they
are stuck with their training data, and before MCP every link to a file system, a database or an API had to be
written by hand for each app. Anthropic released MCP in November 2024 as an open standard to fix that. Few
people cared at first, but by February 2025 there were over 1,000 community servers. The author compares it
to USB or HTTP: one standard everything plugs into, which turns an NxM integration problem into N+M.

MCP has three roles that talk using JSON-RPC 2.0 messages. The host is the LLM application the user works with,
like Claude Desktop or my own agent script. Inside the host there is a client for each server, which keeps the
connection open. The server is a separate program that offers the capabilities. A server can expose tools that
the model decides to call, resources that the application reads as data, and prompts, which are templates the
user picks. The client asks the server what it has, so tools are found at runtime and not hard coded. The
article also says MCP is not an agent framework, only the action part, and it still has problems like security,
running many servers, and models not always using the tools well.

The server I looked at is @redf0x1/mcp-server-filesystem, the one we used in lab 6. It has 12 tools and most of
them are good single-purpose tools: read_file, write_file, move_file, list_directory, get_file_info. Every tool
has an input schema, and errors come back as a clear "Error: ..." message instead of crashing. But some tools
break the principles from class. edit_file edits, checks syntax and, with dryRun=true, only previews, so the same
tool sometimes changes the file and sometimes doesn't. delete_file removes files but also whole folders with a
recursive flag. The worst one is run_command. It runs any shell command and only the working directory is
checked, so it can do everything the other 11 tools do and get around the sandbox they protect. Its description
even calls it secure. Outputs are plain text with no output schema, so the model has to guess the format. I would remove run_command and split edit_file into a preview tool and an
edit tool.

Sources: https://huggingface.co/blog/Kseniase/mcp, https://www.turingpost.com/p/mcp,
https://github.com/redf0x1/MCP-Server-Filesystem
