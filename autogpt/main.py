"""The application entry point.  Can be invoked by a CLI or any other front end application."""
import logging
import sys
from pathlib import Path

from colorama import Fore

from autogpt.agent.agent import Agent
from autogpt.commands.command import CommandRegistry
from autogpt.config import Config, check_openai_api_key
from autogpt.configurator import create_config
from autogpt.logs import logger
from autogpt.memory import get_memory
from autogpt.plugins import scan_plugins
from autogpt.prompts.prompt import DEFAULT_TRIGGERING_PROMPT, construct_main_ai_config
from autogpt.utils import get_current_git_branch, get_latest_bulletin
from autogpt.workspace import Workspace
from scripts.install_plugin_deps import install_plugin_dependencies


def update_config(cfg: Config, **kwargs):
    # Update cfg with the provided kwargs
    for key, value in kwargs.items():
        setattr(cfg, key, value)

    # Call create_config with the updated configuration
    create_config(
        cfg.continuous,
        cfg.continuous_limit,
        cfg.ai_settings,
        cfg.skip_reprompt,
        cfg.speak,
        cfg.debug,
        cfg.gpt3only,
        cfg.gpt4only,
        cfg.memory_type,
        cfg.browser_name,
        cfg.allow_downloads,
        cfg.skip_news,
    )
    # TODO: have this directory live outside the repository (e.g. in a user's
    #   home directory) and have it come in as a command line argument or part of
    #   the env file.
    if workspace_directory is None:
        workspace_directory = Path(__file__).parent / "auto_gpt_workspace"
    else:
        workspace_directory = Path(workspace_directory)
    # TODO: pass in the ai_settings file and the env file and have them cloned into
    #   the workspace directory so we can bind them to the agent.
    workspace_directory = Workspace.make_workspace(workspace_directory)
    cfg.workspace_path = str(workspace_directory)

    # HACK: doing this here to collect some globals that depend on the workspace.
    file_logger_path = workspace_directory / "file_logger.txt"
    if not file_logger_path.exists():
        with file_logger_path.open(mode="w", encoding="utf-8") as f:
            f.write("File Operation Logger ")

    cfg.file_logger_path = str(file_logger_path)

    cfg.set_plugins(scan_plugins(cfg, cfg.debug_mode))
    return cfg


def collect_news():
    motd = get_latest_bulletin()
    if motd:
        logger.typewriter_log("NEWS: ", Fore.GREEN, motd)
    git_branch = get_current_git_branch()
    if git_branch and git_branch != "stable":
        logger.typewriter_log(
            "WARNING: ",
            Fore.RED,
            f"You are running on `{git_branch}` branch "
            "- this is not a supported branch.",
        )
    if sys.version_info < (3, 10):
        logger.typewriter_log(
            "WARNING: ",
            Fore.RED,
            "You are running on an older version of Python. "
            "Some people have observed problems with certain "
            "parts of Auto-GPT with this version. "
            "Please consider upgrading to Python 3.10 or higher.",
        )


def run_auto_gpt(**user_config):
    cfg = update_config(Config(), **user_config)
    # Configure logging before we do anything else.
    logger.set_level(logging.DEBUG if debug else logging.INFO)
    logger.speak_mode = speak

    # TODO: fill in llm values here
    check_openai_api_key()

    if not cfg.skip_news:
        collect_news()

    if install_plugin_deps:
        install_plugin_dependencies()

    # Create a CommandRegistry instance and scan default folder
    command_list = [
        "autogpt.commands.analyze_code",
        "autogpt.commands.audio_text",
        "autogpt.commands.execute_code",
        "autogpt.commands.file_operations",
        "autogpt.commands.git_operations",
        "autogpt.commands.google_search",
        "autogpt.commands.image_gen",
        "autogpt.commands.improve_code",
        "autogpt.commands.twitter",
        "autogpt.commands.web_selenium",
        "autogpt.commands.write_tests",
        "autogpt.app",
    ]
    command_registry = CommandRegistry(command_list)

    ai_name = ""
    ai_config = construct_main_ai_config()
    ai_config.command_registry = command_registry
    # print(prompt)
    # Initialize variables
    full_message_history = []
    next_action_count = 0

    # add chat plugins capable of report to logger
    if cfg.chat_messages_enabled:
        for plugin in cfg.plugins:
            if hasattr(plugin, "can_handle_report") and plugin.can_handle_report():
                logger.info(f"Loaded plugin into logger: {plugin.__class__.__name__}")
                logger.chat_plugins.append(plugin)

    # Initialize memory and make sure it is empty.
    # this is particularly important for indexing and referencing pinecone memory
    memory = get_memory(cfg, init=True)
    logger.typewriter_log(
        "Using memory of type:", Fore.GREEN, f"{memory.__class__.__name__}"
    )
    logger.typewriter_log("Using Browser:", Fore.GREEN, cfg.selenium_web_browser)
    system_prompt = ai_config.construct_full_prompt()
    if cfg.debug_mode:
        logger.typewriter_log("Prompt:", Fore.GREEN, system_prompt)

    agent = Agent(
        ai_name=ai_name,
        memory=memory,
        full_message_history=full_message_history,
        next_action_count=next_action_count,
        command_registry=command_registry,
        config=ai_config,
        system_prompt=system_prompt,
        triggering_prompt=DEFAULT_TRIGGERING_PROMPT,
        workspace_directory=Path(cfg.workspace_path),
    )
    agent.start_interaction_loop()
