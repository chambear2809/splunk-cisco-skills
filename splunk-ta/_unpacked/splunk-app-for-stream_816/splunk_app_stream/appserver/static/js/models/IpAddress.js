define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone"
], function(
    $,
    _,
    Backbone
    ) {
    return Backbone.Model.extend({
        validate: function(attrs, options) {
            var matches;
            var line = attrs.val;

            // IPv4 match
            if (matches = line.match(/^([^.]+)\.([^.]+)\.([^.]+)\.([^.\/]+)(\/(\d+))?$/)) {
                for (var i = 1; i <= 4 ; ++i) {
                    var octet = matches[i]
                    if (octet != '*') {
                        if (! octet.match(/^\d+$/))
                            return "Invalid IPv4 address: octets must be decimal numbers (or wildcards)";
                        if (parseInt(octet) > 255)
                            return "Invalid IPv4 address: octets must be <= 255";
                    }
                }

                if (matches[5]) {
                    var masklen = parseInt(matches[6]);
                    var mask;
                    if (masklen == 0) {
                        mask = 0;
                    } else if (masklen <= 32) {
                        mask = 0xFFFFFFFF << (32 - masklen);
                    } else {
                        return "Invalid IPv4 network: masklen must be <= 32";
                    }

                    var addr =
                        parseInt(matches[1]) << 24| parseInt(matches[2]) << 16 |
                        parseInt(matches[3]) << 8 | parseInt(matches[4]);
                    if ((addr & mask) != addr) {
                        return "Invalid IPv4 network: Host bits must be 0";
                    }
                }

                // Valid IPv4 address
                return;
            // IPv6 match
            } else if (matches = line.match(/^[0-9A-Fa-f:\/]+$/)) {
                var doublecolon = false;
                var count = 0;
                var state = "init";
                var addresses = [];
                var doublecolon_pos = -1;
                var prefixlen = -1;

                // state machine
                while (line.length > 0) {
                    var length;

                    switch (state) {
                    case "init":
                        if (line.match(/^::/)) {
                            doublecolon = true;
                            length = 2;
                            state = "doublecolon";
                        } else if (matches = line.match(/^([0-9A-Fa-f]{1,4})/)) {
                            length = matches[1].length;
                            state = "address";
                        } else {
                            return "Invalid IPv6 address";
                        }
                        break;
                    case "doublecolon":
                        if (line.match(/^\//)) {
                            length = 1;
                            state = "slash";
                        } else if (matches = line.match(/^([0-9A-Fa-f]{1,4})/)) {
                            length = matches[1].length;
                            state = "address";
                        } else {
                            return "Invalid IPv6 address";
                        }
                        break;
                    case "colon":
                        if (matches = line.match(/^([0-9A-Fa-f]{1,4})/)) {
                            length = matches[1].length;
                            state = "address";
                        } else {
                            return "Invalid IPv6 address";
                        }
                        break;
                    case "address":
                        if (line.match(/^\//)) {
                            length = 1;
                            state = "slash";
                        } else if (line.match(/^::/)) {
                            if (doublecolon) {
                                return "Invalid IPv6 address: '::' can appear only once";
                            }
                            doublecolon = true;
                            length = 2;
                            state = "doublecolon";
                        } else if (line.match(/^:/)) {
                            length = 1;
                            state = "colon";
                        } else {
                            return "Invalid IPv6 address";
                        }

                        break;
                    case "slash":
                        if (matches = line.match(/^(\d+)/)) {
                            prefixlen = parseInt(matches[1]);
                            if (prefixlen > 128) {
                                return "Invalid IPv6 address: prefix length must be <= 128";
                            }
                            length = matches[1].length;
                            state = "prefixlen";
                        } else {
                            return "Invalid IPv6 address";
                        }
                        break;
                    case "prefixlen":
                        // there should not be any character after prefixlen
                        return "Invalid IPv6 addess: invalid character after prefix length";
                        break;
                    }

                    // move forward
                    line = line.substring(length);

                    // count address part, double colon implies hidden "0"s
                    if (state == "address") {
                        addresses.push(matches[1]);
                        count++;
                    } else if (state == "doublecolon") {
                        doublecolon_pos = count;
                        count++;
                    }

                    // there must be prefix length after "/"
                    if (state == "slash" && line.length == 0) {
                        return "Invalid IPv6 address: missing prefix length after /";
                    }

                    // too many address parts
                    if (count > 8) {
                        return "Invalid IPv6 address: address is too long";
                    }
                }

                if (!doublecolon && count < 8) {
                    return "Invalid IPv6 address: address is too short";
                }

                // Validate IPv6 prefix with host bits properly masked
                if (prefixlen >= 0) {
                    // replacing "::" with "0"s
                    var zeros = ['0', '0', '0', '0', '0', '0', '0', '0'];
                    if (doublecolon_pos >= 0) {
                        Array.prototype.splice.apply(addresses, [doublecolon_pos, 0].concat(zeros.splice(0, 8 - addresses.length)));
                    }

                    var in6addr = [parseInt(addresses[0], 16) << 16 | parseInt(addresses[1], 16),
                                   parseInt(addresses[2], 16) << 16 | parseInt(addresses[3], 16),
                                   parseInt(addresses[4], 16) << 16 | parseInt(addresses[5], 16),
                                   parseInt(addresses[6], 16) << 16 | parseInt(addresses[7], 16)];
                    var in6mask = [];
                    for (var i = 0; i < 4; ++i) {
                        if (prefixlen == 0) {
                            in6mask.push(0);
                        } else if (prefixlen >= 32) {
                            in6mask.push(0xFFFFFFFF);
                            prefixlen -= 32;
                        } else {
                            in6mask.push(0xFFFFFFFF << (32 - prefixlen));
                            prefixlen = 0;
                        }
                    }

                    for (var i = 0; i < 4; ++i) {
                        if ((in6addr[i] & in6mask[i]) != in6addr[i]) {
                            return "Invalid IPv6 prefix: Host bits must be 0";
                        }
                    }
                }

                // Valid IPv6 address
                return;
            }

            return "Not a valid IPv4 or IPv6 address";
        }
    });
});
