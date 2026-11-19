/**
 * The reading skins that come with FicFairy - offered beside your own in User settings, as a
 * default for works with no skin, and never removable. Each is CSS written as an AO3 work skin is.
 *
 * A skin that loads pictures from another site makes the browser ask that site for them each
 * time a work is opened with it, as AO3 does for a work using it - said beside it in User settings
 * (`remote`).
 */
export interface BuiltInSkin {
  name: string;
  /** what it looks like, in a few words */
  about: string;
  /** whether it loads pictures from another site */
  remote: boolean;
  css: string;
}

export const BUILT_IN_SKINS: readonly BuiltInSkin[] = [
  {
    name: 'Medieval parchment',
    about: 'Parchment behind the text, an illuminated border and a red drop capital.',
    remote: true,
    css: `#workskin {
  background: url("https://64.media.tumblr.com/b435c5f4f58a551bc2a04d3baf0966ec/28df75b586705f4b-be/s1280x1920/5212a899bdbd5f65ccc29ed438adbf5c1fb1f3ee.png");
}

#workskin div.preface {
  margin: 0;
  border-bottom: 2px solid #000;
}

#workskin p:first-child:first-letter,
#workskin #chapters .userstuff p:first-child:first-letter {
  color: #903;
  float: left;
  font-family: Georgia, serif;
  font-size: 75px;
  line-height: 60px;
  padding-top: 4px;
  padding-right: 8px;
  padding-left: 3px;
}

#workskin {
  border: 50px solid transparent;
  border-image: url("https://64.media.tumblr.com/5b41b48ccce874ea293e7503e1dce1fd/ad2373978cc6ca4e-52/s640x960/422f4d1e1b61066e11832919423caba615241c68.png") 25% round;
  color: #2a2a2a;
}

#workskin .preface {
  background: transparent;
  color: #2a2a2a;
}

#workskin .preface a,
#workskin .group .heading {
  color: #2a2a2a;
}`,
  },
  {
    name: 'Frog',
    about: 'Moss green around a cream page with a coral border, Century Gothic, and a frog banner across the top. Adapted from an AO3 site skin, keeping only what a downloaded work has.',
    remote: true,
    css: `body {
  background: #cbd380;
  color: #774120;
  margin: 0;
  padding: 0 4%;
}

#workskin {
  max-width: 50em;
  margin: 2em auto;
  padding: 0 30px 30px;
  background: #f7eee5;
  color: #774120;
  border: 2px solid #d4836e;
  font-family: "Century Gothic", sans-serif;
}

/* AO3's header picture, as a banner across the top of the page */
#workskin::before {
  content: "";
  display: block;
  height: 14em;
  margin: 0 -30px 1.5em;
  background: #d4836e url("https://i.imgur.com/RROXAQE.png") center center / cover no-repeat;
  border-bottom: 2px solid #946549;
}

#workskin h1,
#workskin h2,
#workskin h3,
#workskin .heading {
  font-family: "Century Gothic", sans-serif;
  font-weight: normal;
  font-variant: small-caps;
  color: #d4836e;
}

#workskin a {
  color: #d4836e;
  font-variant: small-caps;
}

#workskin #chapters,
#workskin .userstuff {
  font-family: "Century Gothic", sans-serif;
}

#workskin .meta dl.tags {
  background: #f7eee5;
  border: 2px solid #d4836e;
}

#workskin .meta dl.tags a {
  color: #946549;
}

#workskin .meta.group {
  border-bottom: 3px double #d4836e;
}`,
  },
];
