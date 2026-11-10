# search_notes_by_keyword

**Intent**: Search notes by keyword {keyword} using the notes-list search UI.
**Inputs**: keyword (required): Non-empty text to search for in the notes list.
**Preconditions**: The app is on the main notes list with the search UI closed; Button `resourceId=it.feio.android.omninotes.foss:id/menu_search` (visible description `搜索`) is visible and tappable, and {keyword} is available for entry.
**Postconditions**: The search field `resourceId=it.feio.android.omninotes.foss:id/search_src_text` contains {keyword}; the query indicator `resourceId=it.feio.android.omninotes.foss:id/search_query` shows visible label `搜索: {keyword}`; and the note list is filtered to notes matching {keyword}.
**Effects/Outputs**: The app displays active-search controls `resourceId=it.feio.android.omninotes.foss:id/search_close_btn` (visible description `清除查询`) and `resourceId=it.feio.android.omninotes.foss:id/search_cancel`, plus filtered note rows rendered through `resourceId=it.feio.android.omninotes.foss:id/root` with child TextViews `resourceId=it.feio.android.omninotes.foss:id/note_title`, `resourceId=it.feio.android.omninotes.foss:id/note_content`, and `resourceId=it.feio.android.omninotes.foss:id/note_date`. No persistent note data is changed.
**Steps**:
1. Tap the Button `resourceId=it.feio.android.omninotes.foss:id/menu_search` (visible description `搜索`).
2. Input `{keyword}` into the AutoCompleteTextView `resourceId=it.feio.android.omninotes.foss:id/search_src_text` (visible text/hint `在笔记中搜索`).
3. Press the keyboard Enter key (visible key label `Enter`).
**Evidence**: traces omninotes-search-1; 1/1 successes
