// Pure vanity.

document.addEventListener('DOMContentLoaded', () => justifyLinebreak('.justify-linebreak'));
window.addEventListener('resize', () => justifyLinebreak('.justify-linebreak'));

/**
 * Adds line breaks just before target elements if not doing so would 
 * create a large gap between words in the previous line of justified text.
 * @param {string} selector 
 */
function justifyLinebreak(selector) {
  document.querySelectorAll(selector).forEach(target => {
    const parent = target.parentElement;

    // Don't bother if it's not justified to begin with
    if (getComputedStyle(target).textAlign !== 'justify') return;

    // Clean up: remove any <br> directly before the target
    if (
      target.previousSibling &&
      target.previousSibling.nodeName.toLowerCase() === 'br'
    ) {
      parent.removeChild(target.previousSibling);
    }

    // Get previous node, if it exists
    const nodes = Array.from(parent.childNodes);
    const codeIndex = nodes.indexOf(target);
    if (codeIndex < 1) return;
    let prevNode = nodes[codeIndex - 1];

    // Only handle if previous node is a text node
    if (prevNode.nodeType !== Node.TEXT_NODE) return;

    // Split the text node into words and wrap each in a span
    const words = prevNode.textContent?.split(/(\s+)/) || [];
    const spans = words.map(word => {
      const span = document.createElement('span');
      span.textContent = word;
      return span;
    });

    // Replace the text node with the spans
    spans.forEach(span => parent.insertBefore(span, target));
    parent.removeChild(prevNode);

    // Find the last non-whitespace span before the target
    let lastWordSpan = null;
    let lastWordIndex = spans.length - 1;
    for (let i = spans.length - 1; i >= 0; i--) {
      if (spans[i].textContent?.trim() !== '') {
        lastWordSpan = spans[i];
        lastWordIndex = i;
        break;
      }
    }

    if (!lastWordSpan) return;

    // Find the second to last non-whitespace span before the target
    let secondLastWordSpan = null;
    for (let i = lastWordIndex - 1; i >= 0; i--) {
      if (spans[i].textContent?.trim() !== '') {
        secondLastWordSpan = spans[i];
        break;
      }
    }

    if (!secondLastWordSpan) return;

    // Measure the gap between the last two words
    const lastWordRect = lastWordSpan.getBoundingClientRect();
    const secondLastWordRect = secondLastWordSpan.getBoundingClientRect();

    const gap = lastWordRect.left - secondLastWordRect.right;

    // Get computed font size (in px) of the last word
    const fontSizeStr = window.getComputedStyle(lastWordSpan).fontSize;
    const fontSize = parseFloat(fontSizeStr);

    // Set threshold as a multiple of font size
    const threshold = fontSize * .5;
    
    // If the gap is too big, insert a <br> before the target
    if (gap > threshold) {
      const br = document.createElement('br');
      parent.insertBefore(br, target);
      target = br; // Otherwise cleanup won't work
    }

    // Clean up spans that were created
    const text = spans.map(span => span.textContent).join('');
    const textNode = document.createTextNode(text);
    parent.insertBefore(textNode, target);
    spans.forEach(span => parent.removeChild(span));
  });
}
