from django.apps import AppConfig


class BlogConfig(AppConfig):
    name = 'blog'
    verbose_name = "Управление блогом"

    def ready(self):
        import blog.signals
