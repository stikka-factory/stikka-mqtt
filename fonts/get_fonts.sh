#!/bin/bash

for font in \
    https://github.com/theleagueof/junction/blob/master/Junction-bold.otf \
    https://github.com/theleagueof/junction/blob/master/Junction-light.otf \
    https://github.com/theleagueof/junction/blob/master/Junction-regular.otf \
    https://github.com/theleagueof/junction/blob/master/Junction-regular.otf \
    https://github.com/theleagueof/ostrich-sans/blob/master/OstrichSans-Bold.otf \
    https://github.com/theleagueof/ostrich-sans/blob/master/OstrichSans-Heavy.otf \
    https://github.com/theleagueof/ostrich-sans/blob/master/OstrichSans-Light.otf \
    https://github.com/theleagueof/ostrich-sans/blob/master/OstrichSans-Medium.otf \
    https://github.com/theleagueof/ostrich-sans/blob/master/OstrichSansDashed-Medium.otf \
    https://github.com/theleagueof/ostrich-sans/blob/master/OstrichSansInline-Italic.otf \
    https://github.com/theleagueof/ostrich-sans/blob/master/OstrichSansInline-Regular.otf \
    https://github.com/theleagueof/ostrich-sans/blob/master/OstrichSansInline-Regular.otf \
    https://github.com/theleagueof/fanwood/blob/master/Fanwood%20Italic.otf \
    https://github.com/theleagueof/fanwood/blob/master/Fanwood%20Text%20Italic.otf \
    https://github.com/theleagueof/fanwood/blob/master/Fanwood%20Text%20Italic.otf \
    https://github.com/theleagueof/fanwood/blob/master/Fanwood%20Text%20Italic.otf \
    https://github.com/theleagueof/sorts-mill-goudy/blob/master/OFLGoudyStM-Italic.otf \
    https://github.com/theleagueof/sorts-mill-goudy/blob/master/OFLGoudyStM.otf \
    https://github.com/theleagueof/goudy-bookletter-1911/blob/master/GoudyBookletter1911.otf \
    https://github.com/theleagueof/orbitron/blob/master/Orbitron%20Black.otf \
    https://github.com/theleagueof/orbitron/blob/master/Orbitron%20Bold.otf \
    https://github.com/theleagueof/orbitron/blob/master/Orbitron%20Light.otf \
    https://github.com/theleagueof/orbitron/blob/master/Orbitron%20Medium.otf \
    https://github.com/theleagueof/blackout/blob/master/Blackout%20Midnight.ttf \
    https://github.com/theleagueof/blackout/blob/master/Blackout%20Sunrise.ttf  \
    https://github.com/theleagueof/blackout/blob/master/Blackout%20Two%20AM.ttf \
    https://github.com/theleagueof/linden-hill/blob/master/Linden%20Hill%20Italic.otf \
    https://github.com/theleagueof/linden-hill/blob/master/Linden%20Hill.otf \
    https://github.com/theleagueof/prociono/blob/master/Prociono.otf  \
    https://github.com/theleagueof/knewave/blob/master/knewave-outline.otf \
    https://github.com/theleagueof/knewave/blob/master/knewave.otf \
    https://github.com/theleagueof/league-script-number-one/blob/master/LeagueScriptNumberOne.otf \
    https://github.com/theleagueof/sniglet/blob/master/Sniglet%20Regular.otf \
    https://github.com/theleagueof/chunk/blob/master/ChunkFive-Regular.otf \
    https://github.com/theleagueof/chunk/blob/master/Chunk%20Five%20Print.otf 

do
    ./GitHubFileDownloader.sh $font 
done

echo "Renaming files to clean up spaces in filenames..."
for file in *; 
do 
    newfile=$(echo "$file" | sed 's/%20/_/g'); 
    if [ "$file" != "$newfile" ]; 
        then mv "$file" "$newfile"; 
    fi; 
done