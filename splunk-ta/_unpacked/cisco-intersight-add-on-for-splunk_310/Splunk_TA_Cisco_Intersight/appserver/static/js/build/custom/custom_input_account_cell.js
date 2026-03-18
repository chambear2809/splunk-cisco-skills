const TEMPLATE = `<div title="Missing Account configuration." data-test="alert-icon" style="padding-right: 1px">
<svg
xmlns="http://www.w3.org/2000/svg"
width="16"
height="16"
fill="red"
class="bi bi-exclamation-circle"
viewBox="0 0 16 16"
>
<path
    d="M8 15A7 7 0 1 1 8 1a7 7 0 0 1 0 14zm0 1A8 8 0 1 0 8 0a8 8 0 0 0 0 16z"
/>
<path
    d="M7.002 11a1 1 0 1 1 2 0 1 1 0 0 1-2 0zM7.1 4.995a.905.905 0 1 1 1.8 0l-.35 3.507a.552.552 0 0 1-1.1 0L7.1 4.995z"
/>
</svg>
</div>`;

class CustomInputCell {
    /**
     * Custom Row Cell
     * @constructor
     * @param {Object} globalConfig - Global configuration.
     * @param {string} serviceName - Input service name.
     * @param {element} el - The element of the custom cell.
     * @param {Object} row - custom row object.
     * @param {string} field - The cell field name.
     */
    constructor(globalConfig, serviceName, el, row, field) {
        this.globalConfig = globalConfig;
        this.serviceName = serviceName;
        this.el = el;
        this.row = row;
        this.field = field;
    }
    render() {
        // Check for missing configuration in account
        if (!this.row.global_account || this.row.global_account.trim() === "") {
            this.el.innerHTML = TEMPLATE;
        } else {
            this.el.textContent = this.row.global_account;
        }
        return this;
    }
}
export default CustomInputCell;