# Scoring, favourites and UI

## Automatic score

The V5 station maintains a local 1–7 score for detections. The score is used both as a visual quality/interest indicator and as the basis of the default unliked-retention policy.

The scoring worker runs separately from the acquisition process so processing load and classification failures do not need to stop RTL-SDR acquisition.

## Main UI — 8094

Purpose:

- recent detection list
- score/status display
- rendered waterfall/spectrum view
- pagination
- system/header health information
- navigation to favourites/statistics

## Queue UI — 8095

Purpose:

- visibility into scoring backlog/status
- independent status surface for the scoring pipeline

## Favourites UI — 8096

Purpose:

- filter scores 1–7
- show liked detections
- keep liked detections indefinitely
- manual delete
- bulk remove unliked detections
- click thumbnail to open the same cached detection image in a full-size modal

## Statistics UI — 8097

Purpose:

- daily/24h detection counts
- evaluated detections
- retention activity
- favourites
- scoring queue
- health state
- score-index size
- history/distribution graphs

The final V5 layout intentionally avoids duplicating system tiles already visible on the main MeteorRadio page.
