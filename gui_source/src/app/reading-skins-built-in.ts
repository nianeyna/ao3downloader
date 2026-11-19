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
];
