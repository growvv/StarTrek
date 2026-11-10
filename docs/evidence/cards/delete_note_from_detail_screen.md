# delete_note_from_detail_screen

**Intent**: Delete the note titled {target_note_title} from its detail screen.
**Inputs**: target_note_title (required): Title of the note to delete from the notes list and its detail screen.
**Preconditions**: - The notes list screen is visible and contains a row whose TextView id='it.feio.android.omninotes.foss:id/note_title' displays {target_note_title}. - Opening that row shows a detail screen with EditText id='it.feio.android.omninotes.foss:id/detail_title' displaying {target_note_title} and an ImageView with desc='更多选项'. - The overflow menu for the detail screen contains a delete row with TextView id='it.feio.android.omninotes.foss:id/title' and text='删除记事'.
**Postconditions**: - The detail screen for {target_note_title} is closed and the notes list screen is visible. - No row with TextView id='it.feio.android.omninotes.foss:id/note_title' displays {target_note_title}.
**Effects/Outputs**: - The note titled {target_note_title} is deleted. - The UI returns to the notes list screen.
**Steps**:
1. Tap the TextView id='it.feio.android.omninotes.foss:id/note_title' displaying {target_note_title} in the notes list to open its detail screen.
2. On the detail screen where EditText id='it.feio.android.omninotes.foss:id/detail_title' displays {target_note_title}, tap the ImageView with desc='更多选项'.
3. In the overflow menu, tap the clickable LinearLayout row containing TextView id='it.feio.android.omninotes.foss:id/title' with text='删除记事'.
**Evidence**: traces omninotes-delete-1; 1/1 successes
