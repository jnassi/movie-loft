-- Pulls every movie out of the Apple TV app: a TSV of name/year/director/
-- release date/seconds (the running time feeds the channel guide), plus the
-- cover art the app already has on disk. Art that's already been saved is
-- skipped, so re-runs are quick.
--
--   osascript export.applescript /path/to/repo
--
-- With no argument it uses the folder this script is in.

on run argv
	if (count of argv) > 0 then
		set repoPath to item 1 of argv
	else
		set repoPath to POSIX path of ((path to me as text) & "::")
	end if
	if repoPath does not end with "/" then set repoPath to repoPath & "/"
	set artFolder to repoPath & "art/"
	do shell script "mkdir -p " & quoted form of artFolder

	-- one directory listing beats one `test -e` per film
	set existing to paragraphs of (do shell script ¬
		"ls -1 " & quoted form of artFolder & " 2>/dev/null || true")

	set rowText to ""
	set savedCount to 0
	set skippedCount to 0
	set noArtCount to 0

	tell application "TV"
		-- Each property has to be asked of the app directly. Saving the query to
		-- a variable first and then asking for `name of` it fails with -1728,
		-- because a plain AppleScript list has no `name`. The filter is identical
		-- in all six, so the lists line up.
		set movieList to (every track of library playlist 1 whose media kind is movie)
		set nameList to name of (every track of library playlist 1 whose media kind is movie)
		set yearList to year of (every track of library playlist 1 whose media kind is movie)
		set dirList to director of (every track of library playlist 1 whose media kind is movie)
		set relList to release date of (every track of library playlist 1 whose media kind is movie)
		set durList to duration of (every track of library playlist 1 whose media kind is movie)

		repeat with i from 1 to count of nameList
			set theName to item i of nameList
			set theYear to item i of yearList as text
			set theDir to item i of dirList
			if theDir is missing value then set theDir to ""
			set theRel to item i of relList
			if theRel is missing value then
				set relText to ""
			else
				set relText to my isoDate(theRel)
			end if
			set theDur to item i of durList
			if theDur is missing value then
				set durText to ""
			else
				set durText to (round theDur) as text
			end if
			set rowText to rowText & theName & tab & theYear & tab & theDir & tab & relText & tab & durText & linefeed

			set fileName to my safeName(theName) & ".jpg"
			if existing contains fileName then
				set skippedCount to skippedCount + 1
			else
				set filePath to artFolder & fileName
				try
					set imgData to raw data of artwork 1 of (item i of movieList)
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

	my writeText(rowText, repoPath & "movies.tsv")

	return ((count of paragraphs of rowText) - 1) as text & " movies exported · " & ¬
		(savedCount as text) & " new posters · " & ¬
		(skippedCount as text) & " already saved · " & ¬
		(noArtCount as text) & " without artwork"
end run

on writeText(theText, thePath)
	set fRef to open for access (POSIX file thePath) with write permission
	set eof fRef to 0
	write theText to fRef as «class utf8»
	close access fRef
end writeText

-- release date comes back as an AppleScript date; the TSV wants YYYY-MM-DD
on isoDate(d)
	set y to (year of d) as integer
	set m to (month of d) as integer
	set dd to (day of d) as integer
	return (y as text) & "-" & my pad2(m) & "-" & my pad2(dd)
end isoDate

on pad2(n)
	set s to (n as integer) as text
	if (length of s) < 2 then set s to "0" & s
	return s
end pad2

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
