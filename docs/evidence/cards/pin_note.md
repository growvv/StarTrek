# pin_note

**Intent**: Pin the note titled {target_note_title} through the note-detail overflow menu so it stays at the top of the notes list.
**Inputs**: target_note_title (required): the visible title text to match on the `it.feio.android.omninotes.foss:id/note_title` control for the note to pin.
**Preconditions**: - The notes-list screen is open and contains a clickable `it.feio.android.omninotes.foss:id/root` row whose `it.feio.android.omninotes.foss:id/note_title` is {target_note_title}. - The note is not already pinned; opening the note-detail screen exposes `it.feio.android.omninotes.foss:id/detail_title` and an `ImageView desc='更多选项'` control. - The overflow menu reachable from `ImageView desc='更多选项'` contains the `it.feio.android.omninotes.foss:id/title` item with visible label `text='置顶笔记'`.
**Postconditions**: - The note titled {target_note_title} is pinned and remains in the top/pinned section of the notes list. - The app is on the notes-list screen after one `Back` action, where the `it.feio.android.omninotes.foss:id/note_title` control for {target_note_title} is displayed.
**Effects/Outputs**: - Selecting the `it.feio.android.omninotes.foss:id/title` item with `text='置顶笔记'` sets the pinned state for the opened note; no `it.feio.android.omninotes.foss:id/detail_title` or `it.feio.android.omninotes.foss:id/detail_content` text is edited. - The overflow menu closes; the note-detail screen remains until `Back`, then the notes-list screen with `it.feio.android.omninotes.foss:id/note_title` rows is shown.
**Steps**:
1. Tap the clickable `it.feio.android.omninotes.foss:id/root` row whose `it.feio.android.omninotes.foss:id/note_title` displays {target_note_title}.
2. Tap the `ImageView desc='更多选项'` in the note-detail toolbar where `it.feio.android.omninotes.foss:id/detail_title` displays {target_note_title}.
3. Tap the overflow-menu `it.feio.android.omninotes.foss:id/title` item whose visible label is `text='置顶笔记'`.
4. Press the system `Back` control once.
**Evidence**: traces omninotes-pin-1; 1/1 successes
