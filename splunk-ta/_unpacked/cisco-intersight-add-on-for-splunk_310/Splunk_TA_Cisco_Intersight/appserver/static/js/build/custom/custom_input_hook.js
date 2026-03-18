class CustomInputHook {
    constructor(globalConfig, serviceName, state, mode, util) {
        this.globalConfig = globalConfig;
        this.serviceName = serviceName;
        this.state = state;
        this.mode = mode;
        this.util = util;
        this.previousApiEndpoint = state?.data?.api_endpoint?.value || "";

        // Apply default hide/show logic on load
        this.applyFieldVisibility(this.state?.data?.api_type?.value);
        
        // Initialize metric field names based on current state
        this.updateMetricFieldNames(
            this.state?.data?.metrics_name?.value,
            this.state?.data?.metrics_type?.value,
            this.state?.data?.show_metrics_fields?.value
        );
    }

    // Core logic for controlling field visibility
    applyFieldVisibility(apiType) {
        this.util.setState((prevState) => {
            const newStatereturn = { data: { ...prevState.data } };

            if (apiType === "telemetry") {
                // Other fields
                newStatereturn.data.expand.display = false;
                newStatereturn.data.filter.display = false;
                newStatereturn.data.select.display = false;

                // Telemetry fields
                newStatereturn.data.metrics_type.display = true;
                newStatereturn.data.metrics_name.display = true;
                newStatereturn.data.show_metrics_fields.display = true;
                newStatereturn.data.groupby.display = true;

                newStatereturn.data.api_endpoint.value = "telemetry/TimeSeries";
            } else {
                // Other fields
                newStatereturn.data.expand.display = true;
                newStatereturn.data.filter.display = true;
                newStatereturn.data.select.display = true;

                // Telemetry fields
                newStatereturn.data.metrics_type.display = false;
                newStatereturn.data.metrics_name.display = false;
                newStatereturn.data.show_metrics_fields.display = false;
                newStatereturn.data.groupby.display = false;

                // Restore the previously stored endpoint if it exists
                newStatereturn.data.api_endpoint.value = this.previousApiEndpoint || "";
            }

            return newStatereturn;
        });
    }

    // Generate field name based on metrics_name and type
    generateFieldName(metricsName, metricType) {
        if (!metricsName) {
            return "";
        }
        
        const fieldNameMap = {
            "sum": metricsName,                    // sum uses original name
            "min": `${metricsName}_min`,          // min adds _min suffix
            "max": `${metricsName}_max`,          // max adds _max suffix
            "avg": `${metricsName}/${metricsName}_count`, // avg needs both sum and count
            "latest": metricsName                  // latest uses original name
        };

        return fieldNameMap[metricType] || "";
    }

    // Update metric field names based on selected metrics_type values
    updateMetricFieldNames(metricsName, metricsTypeValue, showMetricsFields) {
        if (!metricsName) {
            return;
        }

        // Parse metrics_type - it can be array or comma-separated string
        let selectedTypes = [];
        if (Array.isArray(metricsTypeValue)) {
            selectedTypes = metricsTypeValue;
        } else if (typeof metricsTypeValue === 'string') {
            selectedTypes = metricsTypeValue.split(',').map(t => t.trim()).filter(t => t);
        }

        // Determine if fields should be visible
        // showMetricsFields can be: true, false, "0", "1", or undefined
        // Default to false if not explicitly set to true or "1"
        const shouldShowFields = showMetricsFields === true || showMetricsFields === "1" || showMetricsFields === 1;

        this.util.setState((prevState) => {
            const newState = { data: { ...prevState.data } };

            // Update each metric type field
            const metricTypes = ['sum', 'min', 'max', 'avg', 'latest'];

            metricTypes.forEach(type => {
                const fieldKey = `metrics_${type}`;

                if (selectedTypes.includes(type)) {
                    // Get existing value from state
                    const existingValue = prevState.data[fieldKey]?.value;

                    // Use existing value if it exists, otherwise generate new one
                    const fieldValue = existingValue || this.generateFieldName(metricsName, type);

                    // Set the value, but control visibility based on show_metrics_fields checkbox
                    newState.data[fieldKey] = {
                        ...prevState.data[fieldKey],
                        display: shouldShowFields,  // Only show if checkbox is checked
                        value: fieldValue           // Always calculate and set the value
                    };
                } else {
                    // Hide the field and clear the value when metric type not selected
                    newState.data[fieldKey] = {
                        ...prevState.data[fieldKey],
                        display: false,
                        value: ""
                    };
                }
            });

            return newState;
        });
    }

    // Called when a field changes
    onChange(event, value, newState) {
        if (event === "api_type") {
            this.applyFieldVisibility(value);
        } else if (event === "metrics_name") {
            // When metrics_name changes, update all metric field names
            const metricsType = newState?.data?.metrics_type?.value;
            const showMetricsFields = newState?.data?.show_metrics_fields?.value;
            this.updateMetricFieldNames(value, metricsType, showMetricsFields);
        } else if (event === "metrics_type") {
            // When metrics_type changes, update visibility and field names
            const metricsName = newState?.data?.metrics_name?.value;
            const showMetricsFields = newState?.data?.show_metrics_fields?.value;
            this.updateMetricFieldNames(metricsName, value, showMetricsFields);
        } else if (event === "show_metrics_fields") {
            // When show_metrics_fields checkbox changes, update field visibility
            const metricsName = newState?.data?.metrics_name?.value;
            const metricsType = newState?.data?.metrics_type?.value;
            this.updateMetricFieldNames(metricsName, metricsType, value);
        }
    }
}

export default CustomInputHook;
