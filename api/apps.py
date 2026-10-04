import os
import sys

from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api'

    def ready(self):
        if any(arg in ('test', 'pytest') for arg in sys.argv):
            return

        manage_py = os.path.basename(sys.argv[0]) == 'manage.py'
        if manage_py:
            if len(sys.argv) < 2 or sys.argv[1] != 'runserver':
                return
            if '--noreload' not in sys.argv and os.environ.get('RUN_MAIN') != 'true':
                return

        from .views import OPTIMIZER_SERVICE

        OPTIMIZER_SERVICE.start_prewarming()
