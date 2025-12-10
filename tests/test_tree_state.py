from L5KTuner.tree_state import TreeState, TreeNodeMeta
from L5KTuner.models import MemberType


def test_tree_state_serialize_restore_roundtrip():
    state = TreeState()
    # build simple meta/check map
    state.set_meta("root", TreeNodeMeta(MemberType.ROOT_CONTROLLER_TAGS, "Controller Tags"))
    state.set_checked("root", True)
    state.set_meta("child", TreeNodeMeta(MemberType.TAG, "Tag1", parent="Controller Tags"))
    state.set_checked("child", False)

    saved = state.serialize()

    # restore into a new TreeState with same meta layout
    state2 = TreeState()
    state2.set_meta("root", TreeNodeMeta(MemberType.ROOT_CONTROLLER_TAGS, "Controller Tags"))
    state2.set_meta("child", TreeNodeMeta(MemberType.TAG, "Tag1", parent="Controller Tags"))
    state2.restore(saved)

    assert state2.get_checked("root") is True
    assert state2.get_checked("child") is False
