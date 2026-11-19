/**
 * The reading skins that come with FicFairy - offered beside your own in User settings, as a
 * default reading skin, and never removable. Each is CSS written as an AO3 work skin is.
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
    about: 'Moss green with a frog banner, the tags in a cream box with coloured tags, and the work on a cream page with a coral border, in Century Gothic. Adapted from an AO3 site skin, keeping what a work page has.',
    remote: true,
    css: `/* the page around the work, as AO3's #outer and #main */
body {
  background: #cbd380;
  color: #774120;
  margin: 0;
  padding: 0 4% 2em;
  font-family: "Century Gothic", sans-serif;
}

/* AO3's header picture, as a banner across the top */
body::before {
  content: "";
  display: block;
  height: 12em;
  margin: 0 -4.2% 1em;
  background: #d4836e url("https://i.imgur.com/RROXAQE.png") center center / cover no-repeat;
  border-top: 2px solid #d4836e;
  border-bottom: 2px solid #946549;
}

p.message {
  font-size: 0.85em;
  text-align: center;
}

p.message a {
  color: #946549;
}

h1, h2, h3, h4, h5, h6, .heading {
  font-family: "Century Gothic", sans-serif;
  font-weight: normal;
}

/* the tags box */
dl.work.meta {
  max-width: 50em;
  margin: 1em auto;
  padding: 1em 1.5em;
  background: #f7eee5;
  border: 2px solid #d4836e !important;
}

dl.meta a {
  color: #946549;
  text-decoration: none;
  border-bottom: 1px dotted;
}

dt.warning.tags,
dd.warning.tags a {
  color: #634279 !important;
  font-weight: bold;
}

dt.relationship.tags,
dd.relationship.tags a {
  color: #897b38 !important;
}

dt.character.tags,
dd.character.tags a {
  color: #e5802f !important;
}

dt.freeform.tags,
dd.freeform.tags a {
  color: #22739d !important;
}

/* the work */
#workskin {
  max-width: 50em;
  margin: 0 auto;
  padding: 0 30px 30px;
  background: #f7eee5;
  border: 2px solid #d4836e;
  color: #774120;
}

#workskin h2,
#workskin a {
  color: #d4836e;
  font-variant: small-caps;
}

#workskin div.preface {
  margin: 0;
  padding: 0;
  border-bottom: 3px double #d4836e;
}

#workskin .preface .title {
  text-align: center;
  font-size: 2em;
  margin: 0.6em 0 0.2em;
}

#workskin .preface .byline {
  text-align: center;
  color: #d4836e;
  font-variant: small-caps;
  font-size: 1.2em;
}

#workskin .preface .byline a {
  text-decoration: none;
}

#workskin .preface .module .heading {
  border-bottom: 1px solid #774120;
  margin: 1em 0 0.5em;
  font-size: 1.2em;
}

#workskin .preface blockquote {
  margin: 0 0 1em 1em;
  padding: 0;
}

/* the download pads both the chapters and each chapter's text - once is AO3's */
#workskin #chapters {
  padding: 0;
}

#workskin #chapters,
#workskin .userstuff {
  font-family: "Century Gothic", sans-serif;
}`,
  },
];
