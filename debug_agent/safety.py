class SafetyGuard:
    """
    AI Debug Agent safety controller

    Phase 1:
    read_only mode only
    """

    MODE = "read_only"

    @classmethod
    def can_modify_file(cls):
        return False

    @classmethod
    def can_git_commit(cls):
        return False

    @classmethod
    def can_git_push(cls):
        return False

    @classmethod
    def can_deploy(cls):
        return False