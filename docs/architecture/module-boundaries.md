# Module boundaries

| Logical module | Actual location | Primary entry |
| --- | --- | --- |
| robot_backend | web_console.py, autodrive_console/, live_preprocessor/ | web_console.py |
| web_console | frontend/ | npm run dev; Vite output is served by backend |
| mobile | mobile/ | lib/main.dart |
| unity (paused) | unity/ and mobile/packages/aletheia_visualization/ | no default entry |

Contracts belong in ../../shared/contracts/. This is a logical Monorepo boundary; source has not moved.
