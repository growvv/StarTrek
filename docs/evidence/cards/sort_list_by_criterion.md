# sort_list_by_criterion

**Intent**: Sort the {list_label} by {sort_criterion} using the sort menu option displayed as {sort_option_label}.
**Inputs**: list_label (required): name or context of the list screen to be sorted; referenced as {list_label}., sort_criterion (required): semantic criterion requested for {list_label}; referenced as {sort_criterion}., sort_option_label (required): visible label of the sort-menu row corresponding to {sort_criterion}; referenced as {sort_option_label}.
**Preconditions**: The {list_label} screen is visible; the sort button with resourceId=it.feio.android.omninotes.foss:id/menu_sort is available; the sort-options menu can be opened and includes a clickable row whose TextView has resourceId=it.feio.android.omninotes.foss:id/title and displays {sort_option_label}.
**Postconditions**: The {list_label} is sorted by {sort_criterion}; the sort menu option displayed as {sort_option_label} is the active selection and the sort-options menu is closed.
**Effects/Outputs**: The sort-options menu is dismissed; the {list_label} view is re-rendered in {sort_criterion} order after {sort_option_label} is selected.
**Steps**:
1. On the {list_label} screen, tap the sort button with resourceId=it.feio.android.omninotes.foss:id/menu_sort to open the sort-options menu.
2. Tap the sort-option row whose TextView has resourceId=it.feio.android.omninotes.foss:id/title and visible label {sort_option_label} to apply the {sort_criterion} sort.
**Evidence**: traces omninotes-sort-1; 1/1 successes
