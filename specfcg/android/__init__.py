"""Device-independent Android helpers.

Nothing here talks to a device.  These are the pieces both the executor and
the screenshot-first agent need — UI-tree compaction, launch-state settling,
data seeding — and they live in their own package so neither side has to
import the other.  Before this package existed, `mobile_agent` imported
`specfcg.executor.ui` while `specfcg` imported `mobile_agent`, which is a
package-level import cycle: it worked only because the specific names
happened to resolve, and any reordering of imports could break it.
"""
