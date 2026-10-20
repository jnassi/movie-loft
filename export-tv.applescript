-- Pulls every TV episode out of the Apple TV app: a TSV with one row per episode
-- (show, season, episode, title, seconds, year), plus one cover image per show
-- taken from its earliest episode. Art that's already been saved is skipped,
-- so re-runs are quick.
--
--   osascript export-tv.applescript /path/to/repo
--
-- With no argument it uses the folder this script is in.

on run argv
	if (count of argv) > 0 then
		set repoPath to item 1 of argv
	else
		set repoPath to POSIX path of ((path to me as text) & "::")
	end if
	if repoPath does not end with "/" then set repoPath to repoPath & "/"
	set artFolder to repoPath & "art-tv/"
	do shell script "mkdir -p " & quoted form of artFolder

	set existing to paragraphs of (do shell script ¬
		"ls -1 " & quoted form of artFolder & " 2>/dev/null || true")

	set rowList to {} -- joined once at the end; growing one string 7,000 times is quadratic
	set savedCount to 0
	set skippedCount to 0
	set noArtCount to 0

	tell application "TV"
		with timeout of 600 seconds
			-- Same rule as the movie export: ask the app for each property of the
			-- whole query, never of a saved list (that fails with -1728). The
			-- filter is identical in every line, so the lists line up.
			set epList to (every track of library playlist 1 whose media kind is TV show)
			set showList to show of (every track of library playlist 1 whose media kind is TV show)
			set seasonList to season number of (every track of library playlist 1 whose media kind is TV show)
			set epNumList to episode number of (every track of library playlist 1 whose media kind is TV show)
			set nameList to name of (every track of library playlist 1 whose media kind is TV show)
			set durList to duration of (every track of library playlist 1 whose media kind is TV show)
			set yearList to year of (every track of library playlist 1 whose media kind is TV show)
		end timeout
	end tell

	-- Rows, plus the earliest (season, episode) per show for its cover art.
	set shows to {}
	set bestIdx to {}
	set bestRank to {}
	repeat with i from 1 to count of showList
		set theShow to item i of showList
		if theShow is missing value or theShow is "" then set theShow to "Unknown Show"
		set s to item i of seasonList
		if s is missing value then set s to 0
		set e to item i of epNumList
		if e is missing value then set e to 0
		set nm to item i of nameList
		if nm is missing value then set nm to ""
		set d to item i of durList
		if d is missing value then set d to 0
		set y to item i of yearList
		if y is missing value then set y to 0
		set end of rowList to theShow & tab & (s as text) & tab & (e as text) & tab & nm & ¬
			tab & ((round d) as text) & tab & (y as text)

		set rank to s * 10000 + e
		set k to my indexOf(theShow, shows)
		if k is 0 then
			set end of shows to theShow
			set end of bestIdx to i
			set end of bestRank to rank
		else if rank < (item k of bestRank) then
			set item k of bestIdx to i
			set item k of bestRank to rank
		end if
	end repeat

	tell application "TV"
		repeat with k from 1 to count of shows
			set fileName to my safeName(item k of shows) & ".jpg"
			if existing contains fileName then
				set skippedCount to skippedCount + 1
			else
				set filePath to artFolder & fileName
				try
					set imgData to raw data of artwork 1 of (item (item k of bestIdx) of epList)
					set fRef to open for access (POSIX file filePath) with write permission
					set eof fRef to 0
					write imgData to fRef
					close access fRef
					set savedCount to savedCount + 1
				on error
					try
						close access (POSIX file filePath)
					end try
					set noArtCount to noArtCount + 1
				end try
			end if
		end repeat
	end tell

	set AppleScript's text item delimiters to linefeed
	set rowText to (rowList as text) & linefeed
	set AppleScript's text item delimiters to ""
	my writeText(rowText, repoPath & "episodes.tsv")

	return ((count of showList) as text) & " episodes from " & ((count of shows) as text) & ¬
		" shows exported · " & (savedCount as text) & " new covers · " & ¬
		(skippedCount as text) & " already saved · " & (noArtCount as text) & " without artwork"
end run

on indexOf(x, lst)
	repeat with i from 1 to count of lst
		if item i of lst is x then return i
	end repeat
	return 0
end indexOf

on writeText(theText, thePath)
	set fRef to open for access (POSIX file thePath) with write permission
	set eof fRef to 0
	write theText to fRef as «class utf8»
	close access fRef
end writeText

-- ":" and "/" can't go in a filename; the page applies the same swap
on safeName(theName)
	set out to ""
	repeat with c in characters of theName
		set ch to c as text
		if ch is ":" or ch is "/" then
			set out to out & "_"
		else
			set out to out & ch
		end if
	end repeat
	return out
end safeName
