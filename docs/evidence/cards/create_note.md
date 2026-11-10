# create_note

**Intent**: Create and save a text note titled {note_title} with content {note_content}.
**Inputs**: note_title (required): Text to use as the new note title., note_content (required): Text to use as the new note content.
**Preconditions**: The notes list screen labeled `笔记` is open with `it.feio.android.omninotes.foss:id/list` visible, and the floating action menu is collapsed with `it.feio.android.omninotes.foss:id/fab_expand_menu_button` available.
**Postconditions**: The notes list screen labeled `笔记` is shown, and a saved note card in `it.feio.android.omninotes.foss:id/list` has `it.feio.android.omninotes.foss:id/note_title` set to {note_title} and `it.feio.android.omninotes.foss:id/note_content` set to {note_content}.
**Effects/Outputs**: A new text note is persisted and appears as a note card; the editor and keyboard are dismissed, and the app returns to the notes list labeled `笔记`.
**Steps**:
1. Click `it.feio.android.omninotes.foss:id/fab_expand_menu_button` to expand the floating action menu.
2. Click the `文本注释` action button `it.feio.android.omninotes.foss:id/fab_note` to open the text note editor.
3. Input {note_title} into the title field `it.feio.android.omninotes.foss:id/detail_title` with visible label `标题`.
4. Input {note_content} into the content field `it.feio.android.omninotes.foss:id/detail_content` with visible label `内容`.
5. Press the system `Back` key once to dismiss the on-screen keyboard.
6. Press the system `Back` key once to save the note and return from `it.feio.android.omninotes.foss:id/detail_root` to the notes list labeled `笔记`.
**Evidence**: traces omninotes-create-note-2; 1/1 successes
