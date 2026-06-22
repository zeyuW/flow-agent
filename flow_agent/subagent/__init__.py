"""Subagent module: background task delegation with async spawn + MessageBus completion.

Manager    — SubagentManager: async spawn/spawn_sync, _run_subagent, _announce_result
SubAgent   — async LLM tool loop with completion detection, max_iterations
Runner     — AgentBackgroundJobRunner: lifecycle wrapper
Profiles   — build_spawn_spec, PROFILE_RESEARCH/SCRIPTING/GENERAL
SpawnTool  — main agent tool with DelegationPolicy + background/sync modes
"""
