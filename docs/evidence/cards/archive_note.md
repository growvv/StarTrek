# archive_note

**Intent**: Archive the note selected by `{target_note}` using the note detail overflow menu.
**Inputs**: target_note (required): Visible title or disambiguating locator for the note to archive in the active notes list, matched through `resourceId=it.feio.android.omninotes.foss:id/note_title`.
**Preconditions**: - The active notes list with `TextView text='笔记'` is displayed. - A note row with `FrameLayout id='it.feio.android.omninotes.foss:id/root'` contains the `resourceId=it.feio.android.omninotes.foss:id/note_title` control for `{target_note}`. - The note detail screen has the `ImageView desc='更多选项'` control, and its overflow menu includes the item with visible label `text='归档'`.
**Postconditions**: - The note selected by `{target_note}` is archived and no longer appears in the active notes list. - The note detail screen and overflow menu are closed, and the active notes list with `TextView text='笔记'` is displayed.
**Effects/Outputs**: - The app records the archive state for the note selected by `{target_note}`. - The UI returns to the active notes list.
**Steps**:
1. Click the `resourceId=it.feio.android.omninotes.foss:id/note_title` control inside the `FrameLayout id='it.feio.android.omninotes.foss:id/root'` row for the note selected by `{target_note}`.
2. Click the `ImageView desc='更多选项'` control in the note detail toolbar.
3. Click the overflow menu item with visible label `text='归档'` and `TextView id='it.feio.android.omninotes.foss:id/title'`.
**Evidence**: traces omninotes-archive-1; 1/1 successes
