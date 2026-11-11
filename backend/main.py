# Preserve both "backend.main:app" and "main:app" from inside backend/.
if __package__:
    from .ups_monitor.presentation.app import create_app
else:
    from ups_monitor.presentation.app import create_app


app = create_app()
