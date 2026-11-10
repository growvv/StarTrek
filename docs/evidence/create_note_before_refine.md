# create_note

**Intent**: Create a text note titled {note_title} with content {note_content}.
**Inputs**: note_title (required): Title text to store for the new note., note_content (required): Body text to store for the new note.
**Preconditions**: - The Omni Notes app is open on the notes list screen. - The expandable floating action menu is available. - A text-note editor is not already active.
**Postconditions**: - A saved note with title {note_title} and content {note_content} is present. - The app is back on the notes list screen, where the note card for {note_title} and {note_content} is visible.
**Effects/Outputs**: - A new text note record is created and persisted. - The note editor is closed, leaving the list view active.
**Steps**:
1. Open the floating action menu via `it.feio.android.omninotes.foss:id/fab_expand_menu_button` if it is not already expanded.
2. Select the text-note creation action `it.feio.android.omninotes.foss:id/fab_note` to open a blank note editor.
3. Enter {note_title} into the title field `it.feio.android.omninotes.foss:id/detail_title`.
4. Enter {note_content} into the content field `it.feio.android.omninotes.foss:id/detail_content`.
5. Use back navigation from the editor, repeating as needed until the notes list is displayed; this commits the new note on exit.
**Evidence**: traces evidence: `omninotes-create-note-2`. The trace shows the creation flow through `fab_expand_menu_button` → `fab_note` → `detail_title`/`detail_content`, omninotes-create-note-2; 1/1 successes
