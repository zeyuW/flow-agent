"""FlowAgent session management module.

Session lifecycle: SessionManager cache + SessionStore SQLite persistence.

- session_models: Session, SessionMeta data models
- session_store: SessionStore (sessions table, message CRUD, cursor mgmt)
- session_manager: SessionManager (cache, get_or_create, async locks)
- history_builder: get_history() rebuild OpenAI-format history
- undo: /undo command (delete last turn, rollback cursor, cleanup memory)
"""
