# open_note_by_title

**Intent**: Open the note whose title is {note_title}.
**Inputs**: note_title (required): Visible title of the target note, used to identify the note entry in the notes list.
**Preconditions**: The notes list is displayed and contains a visible note entry with TextView id='it.feio.android.omninotes.foss:id/note_title' whose visible label is {note_title}.
**Postconditions**: The note detail screen for {note_title} is open, and EditText id='it.feio.android.omninotes.foss:id/detail_title' displays {note_title}.
**Effects/Outputs**: The selected note is presented in its detail view/editor; the title control EditText id='it.feio.android.omninotes.foss:id/detail_title' is visible.
**Steps**:
1. Tap the TextView id='it.feio.android.omninotes.foss:id/note_title' whose visible label is {note_title}.
**Evidence**: traces omninotes-open-note-1, omninotes-share-1; 2/2 successes
